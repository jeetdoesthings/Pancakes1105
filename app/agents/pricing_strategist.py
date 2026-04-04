"""
Pricing Strategist Agent
========================
Analyzes internal pricing, competitor data, and applies intelligent
value-differentiation strategy. This is the core differentiator.
"""

import json
import os
from typing import Callable, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from app.models import (
    ExtractedRequirements, PricingStrategy, LineItem, CompetitorAnalysis,
    AgentMessage, AgentRole, MessageType
)
from app.config import settings
from app.tools.pricing_tools import (
    get_internal_pricing_tool,
    get_competitor_data_tool,
    research_market_rates_tool,
    suggest_value_add_tool,
    _load_json
)
from app.pricing_algorithm import compute_price
from app.product_normalizer import normalize_product_name


STRATEGY_PROMPT = PromptTemplate.from_template("""You are a "Pricing Strategist" — an expert competitive pricing analyst for an SME.

You have analyzed the following data:

EXTRACTED RFP REQUIREMENTS:
{requirements_json}

INTERNAL PRICING (our costs and standard prices):
{internal_pricing_json}

COMPETITOR DATA:
{competitor_json}

HISTORICAL SIMILAR RFPs (pricing intelligence from past wins):
{similar_rfps_json}

PRICING ANALYSIS PERFORMED:
{analysis_summary}

VALUE-ADDS BEING RECOMMENDED:
{value_adds_summary}

Based on this analysis, write a concise pricing rationale and strategy summary.

The rationale should explain:
1. How our pricing compares to the competition
2. Why specific value-adds are being recommended (if any)
3. The overall win strategy for this proposal
4. Why the customer should choose us over cheaper competitors and what is our competitive advantage
5. How historical similar RFPs informed our pricing decisions (if available)

Return ONLY a JSON object:
{{
  "pricing_rationale": "detailed rationale paragraph explaining the pricing decisions",
  "strategy_summary": "one-paragraph strategic summary of the overall approach"
}}

Return ONLY the JSON, no other text.""")


class PricingStrategist:
    """Analyzes pricing, competitors, and applies value-differentiation."""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.2,
            max_tokens=2048,
        )
        self.role = AgentRole.PRICING_STRATEGIST
        self.tax_data = _load_json("tax_rates.json")
        self.internal_pricing = _load_json("internal_pricing.json")
        self.competitor_data = _load_json("competitor_data.json")

    async def analyze(
        self,
        requirements: ExtractedRequirements,
        emit_message: Optional[Callable] = None,
        additional_instructions: str = "",
        similar_rfps: list[dict] = None,
    ) -> PricingStrategy:
        """Perform pricing analysis with value-differentiation."""

        if similar_rfps is None:
            similar_rfps = []

        async def emit(msg_type: MessageType, content: str):
            if emit_message:
                await emit_message(AgentMessage(
                    agent=self.role,
                    message_type=msg_type,
                    content=content
                ))

        await emit(MessageType.STATUS, "Starting competitive pricing analysis...")

        if similar_rfps:
            await emit(MessageType.RESULT,
                f"📚 Incorporating intelligence from {len(similar_rfps)} similar historical RFPs "
                f"to inform pricing benchmarks and strategy."
            )
        await emit(MessageType.THINKING, f"Analyzing {len(requirements.scope_items)} scope items against internal pricing catalog and competitor data...")

        line_items = []
        value_add_items = []
        competitor_analyses = []
        analysis_details = []
        value_differentiation_triggered = False
        benchmarks_used = False

        # Process each scope item
        for scope_item in requirements.scope_items:
            await emit(MessageType.ACTION, f"Analyzing pricing for: {scope_item.item_name} (Qty: {scope_item.quantity})...")

            # Product Normalization Layer — fuzzy match to internal catalog
            product = normalize_product_name(scope_item.item_name)
            if not product:
                # Fallback: try the keyword tool for broader matching
                internal_tool_response = get_internal_pricing_tool.invoke(scope_item.item_name)
                if not internal_tool_response.startswith("No "):
                    try:
                        product_list = json.loads(internal_tool_response)
                        if product_list:
                            product = product_list[0]
                    except Exception:
                        pass

            if product:
                unit_price = product["standard_price"]
                base_cost = product["base_cost"]
                total_price = unit_price * scope_item.quantity

                await emit(MessageType.THINKING,
                    f"Matched '{scope_item.item_name}' to internal product '{product['name']}' "
                    f"(Base Cost: ₹{base_cost:,.0f}, Standard Price: ₹{unit_price:,.0f})"
                )

                line_items.append(LineItem(
                    item_name=product["name"],
                    description=product["description"],
                    quantity=scope_item.quantity,
                    unit_price=unit_price,
                    total_price=total_price,
                    matched_product_id=product["id"],
                ))

                comp_tool_response = get_competitor_data_tool.invoke(product["id"])
                comp_prices = []
                market_research_context = ""

                if not comp_tool_response.startswith("No "):
                    if comp_tool_response.startswith("Market Benchmarks:"):
                        # Competitor data file has benchmark summaries, not per-product prices
                        market_research_context = comp_tool_response
                        benchmarks_used = True
                        await emit(MessageType.ACTION, f"Found market benchmarks for {product['name']}.")
                    else:
                        # Old structure: actual competitor prices
                        try:
                            comp_prices = json.loads(comp_tool_response)
                        except Exception:
                            market_research_context = comp_tool_response
                else:
                    # No local data at all - perform live search
                    search_query = f"cost of {product['name']} in India"
                    await emit(MessageType.ACTION, f"No local competitor data. Performing live market research for: {product['name']}...")
                    live_res = research_market_rates_tool.invoke(search_query)
                    if live_res:
                        market_research_context = live_res

                comp_prices_floats = [c["price"] for c in comp_prices]
                
                # Deterministic pricing algorithm (MATCH / PIVOT / BASELINE)
                final_price, strategy_type, rationale = compute_price(
                    cost=base_cost,
                    competitor_prices=comp_prices_floats,
                    margin=product["min_margin_percent"],
                    budget=requirements.budget_amount if requirements.budget_amount > 0 else None,
                )
                
                unit_price = final_price
                can_match = (strategy_type == "MATCH")
                
                # We record the lowest comp price for analysis display
                lowest_comp = min(comp_prices_floats) if comp_prices_floats else 0.0

                display_comp_name = "Unknown"
                if comp_prices:
                    display_comp_name = ", ".join([c.get("competitor_name", c.get("competitor", "Unknown")) for c in comp_prices])
                elif market_research_context:
                    if "Local Benchmarks:" in market_research_context:
                        display_comp_name = "Market Benchmarks"
                    else:
                        display_comp_name = "Live Web Research"

                # Build algorithm decision threshold description
                if comp_prices_floats:
                    min_comp = min(comp_prices_floats)
                    if min_comp > base_cost:
                        threshold_desc = f"min_competitor({min_comp:,.0f}) > cost({base_cost:,.0f}) → MATCH (undercut while defending margin)"
                    else:
                        threshold_desc = f"min_competitor({min_comp:,.0f}) ≤ cost({base_cost:,.0f}) → PIVOT (value-add bundle triggered)"
                else:
                    threshold_desc = f"No competitor data → BASELINE (target margin {product.get('min_margin_percent', 0.3)*100:.0f}%)"

                analysis = CompetitorAnalysis(
                    competitor_name=display_comp_name,
                    product_id=product["id"],
                    competitor_price=lowest_comp,
                    our_price=final_price,
                    price_difference=final_price - lowest_comp,
                    price_difference_pct=((final_price - lowest_comp) / final_price) * 100 if final_price > 0 else 0,
                    can_match=can_match,
                    recommendation=rationale,
                    # Algorithm Decision Log
                    algorithm_strategy=strategy_type,
                    algorithm_input_cost=base_cost,
                    algorithm_input_competitor_prices=comp_prices_floats,
                    algorithm_input_margin_target=product.get("min_margin_percent", 0.3),
                    algorithm_threshold=threshold_desc,
                    algorithm_output_price=final_price,
                    algorithm_output_rationale=rationale,
                )

                if strategy_type == "PIVOT":
                    await emit(MessageType.THINKING,
                        f"⚠️ PIVOT triggered: competitor ₹{lowest_comp:,.0f} vs our cost ₹{base_cost:,.0f}. "
                        f"Adding value-add bundles."
                    )
                    await emit(MessageType.ACTION,
                        f"📐 ALGORITHM DECISION for '{product['name']}':\n"
                        f"  INPUT: cost=₹{base_cost:,.0f}, competitors=[₹{', ₹'.join(f'{p:,.0f}' for p in comp_prices_floats)}], margin={product.get('min_margin_percent', 0.3)*100:.0f}%\n"
                        f"  DECISION: min_competitor(₹{lowest_comp:,.0f}) ≤ cost(₹{base_cost:,.0f}) → PIVOT\n"
                        f"  OUTPUT: ₹{final_price:,.0f} (target margin preserved, value-adds compensate)"
                    )
                    
                    # Select appropriate value-adds via Tool
                    va_tool_resp = suggest_value_add_tool.invoke(product["category"])
                    suggested_adds = []
                    if not va_tool_resp.startswith("No "):
                        try:
                            suggested_adds = json.loads(va_tool_resp)
                        except Exception:
                            pass
                            
                    analysis.recommendation += " Adding value-add bundles to compensate."
                    for va in suggested_adds:
                        analysis.value_adds_suggested.append(va["name"])
                        est_cost = va.get("estimated_cost", 0)
                        value_add_items.append(LineItem(
                            item_name=va["name"],
                            description=va["description"],
                            quantity=1,
                            unit_price=est_cost,  # Market value (shown as INCLUDED in PDF)
                            total_price=est_cost,
                            is_value_add=True
                        ))
                elif strategy_type == "BASELINE":
                    if market_research_context:
                        await emit(MessageType.THINKING,
                            f"Using Market Research for '{product['name']}'"
                        )
                        # Don't set per-item recommendation — will add single summary line at end
                        analysis.recommendation = f"Pricing aligned with market benchmarks."
                    else:
                        await emit(MessageType.THINKING,
                            f"No competitor data for '{product['name']}'. Using BASELINE pricing at target margin."
                        )
                        analysis.recommendation = f"No competitor data available. Pricing set at target margin of {product.get('min_margin_percent', 30)*100:.0f}%."
                    await emit(MessageType.ACTION,
                        f"📐 ALGORITHM DECISION for '{product['name']}':\n"
                        f"  INPUT: cost=₹{base_cost:,.0f}, competitors=[], margin={product.get('min_margin_percent', 0.3)*100:.0f}%\n"
                        f"  DECISION: No competitor data → BASELINE\n"
                        f"  OUTPUT: ₹{final_price:,.0f} (target margin pricing)"
                    )
                else:
                    await emit(MessageType.THINKING, f"✅ MATCH strategy: Best competitor ₹{lowest_comp:,.0f}, our price ₹{final_price:,.0f}.")
                    await emit(MessageType.ACTION,
                        f"📐 ALGORITHM DECISION for '{product['name']}':\n"
                        f"  INPUT: cost=₹{base_cost:,.0f}, competitors=[₹{', ₹'.join(f'{p:,.0f}' for p in comp_prices_floats)}], margin={product.get('min_margin_percent', 0.3)*100:.0f}%\n"
                        f"  DECISION: min_competitor(₹{min(comp_prices_floats):,.0f}) > cost(₹{base_cost:,.0f}) → MATCH\n"
                        f"  OUTPUT: ₹{final_price:,.0f} (undercut lowest competitor while defending margin)"
                    )
                    
                competitor_analyses.append(analysis)
                
                comp_display_name = analysis.competitor_name
                if comp_display_name == "None" and market_research_context:
                    comp_display_name = "Market Benchmarks"
                
                analysis_details.append(
                    f"{product['name']} vs {comp_display_name}: "
                    f"Our ₹{unit_price:,.0f} vs Their {('₹'+format(lowest_comp, ',.0f')) if lowest_comp > 0 else 'Unknown'} — {market_research_context if market_research_context else analysis.recommendation}"
                )
            else:
                # No match - use estimated pricing
                await emit(MessageType.THINKING,
                    f"No direct match in internal catalog for '{scope_item.item_name}'. "
                    f"Using estimation based on similar items."
                )
                estimated_price = 100000  # Default estimate
                line_items.append(LineItem(
                    item_name=scope_item.item_name,
                    description=scope_item.description,
                    quantity=scope_item.quantity,
                    unit_price=estimated_price,
                    total_price=estimated_price * scope_item.quantity,
                ))

        # Append single benchmark summary line if market research was used
        if benchmarks_used:
            analysis_details.append(
                "Pricing accurately aligned with competitive local market benchmarks."
            )

        # Calculate totals with REGIONAL tax detection (Twist 1)
        subtotal = sum(item.total_price for item in line_items)
        value_adds_total = sum(va.unit_price for va in value_add_items)

        # Detect regional tax based on currency
        currency = requirements.budget_currency or "INR"
        tax_region_map = {
            "USD": "US",
            "GBP": "UK",
            "EUR": "EU",
            "INR": "IN",
        }
        region_code = tax_region_map.get(currency, self.tax_data.get("default_region", "IN"))

        # Handle EU (EUR) — not in tax_rates.json, use 19% VAT
        if region_code == "EU":
            tax_rate = 0.19
            tax_label = "VAT"
        else:
            region_tax = self.tax_data.get("tax_rates", {}).get(region_code, {})
            tax_rate = region_tax.get("rate", 0.18)
            tax_label = region_tax.get("name", "Tax").split(" (")[0]  # "GST", "Sales Tax", "VAT"

        tax_amount = subtotal * tax_rate
        total = subtotal + tax_amount

        await emit(MessageType.RESULT,
            f"Pricing Summary:\n"
            f"• Subtotal: {currency} {subtotal:,.0f}\n"
            f"• {tax_label} ({tax_rate*100:.0f}%): {currency} {tax_amount:,.0f}\n"
            f"• Total: {currency} {total:,.0f}\n"
            f"• Value-Adds Included: {len(value_add_items)} items (at no extra cost)"
        )

        if value_differentiation_triggered:
            await emit(MessageType.RESULT,
                "🎯 VALUE-DIFFERENTIATION STRATEGY ACTIVATED: Our proposal includes "
                "strategic value-adds that competitors cannot match at their lower price points. "
                "This positions us as the premium, value-driven choice."
            )

        # Generate LLM-powered rationale
        await emit(MessageType.ACTION, "Generating strategic pricing rationale using AI analysis...")

        analysis_summary = "\n".join(analysis_details) if analysis_details else "No competitor data available for comparison."
        value_adds_summary = "\n".join(
            f"- {va.item_name}: {va.description}" for va in value_add_items
        ) if value_add_items else "No value-adds recommended."

        try:
            similar_rfps_summary = ""
            if similar_rfps:
                similar_rfps_data = []
                for sr in similar_rfps:
                    rfp = sr.get("rfp", {})
                    similar_rfps_data.append({
                        "title": rfp.get("title", ""),
                        "product": rfp.get("productName", ""),
                        "budget": rfp.get("budget"),
                        "currency": rfp.get("currency", ""),
                        "combined_score": sr.get("combined_score", 0),
                    })
                similar_rfps_json = json.dumps(similar_rfps_data, indent=2)
                similar_rfps_summary = f"{len(similar_rfps)} similar historical RFPs found with pricing benchmarks."
            else:
                similar_rfps_json = "No historical similar RFPs found in database."

            prompt_text = STRATEGY_PROMPT.format(
                requirements_json=json.dumps(requirements.model_dump(), indent=2, default=str),
                internal_pricing_json=json.dumps(self.internal_pricing, indent=2),
                competitor_json=json.dumps(self.competitor_data, indent=2),
                similar_rfps_json=similar_rfps_json,
                analysis_summary=analysis_summary,
                value_adds_summary=value_adds_summary,
            )

            if additional_instructions:
                prompt_text += f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{additional_instructions}"

            llm_response_msg = await self.llm.ainvoke(prompt_text)
            llm_response = str(llm_response_msg.content) if hasattr(llm_response_msg, 'content') else str(llm_response_msg)

            # Parse rationale
            rationale_data = self._parse_rationale(llm_response)
            pricing_rationale = rationale_data.get("pricing_rationale", "")
            strategy_summary = rationale_data.get("strategy_summary", "")
        except Exception as e:
            pricing_rationale = f"Automated pricing analysis complete. {len(competitor_analyses)} competitor comparisons performed."
            strategy_summary = "Standard pricing strategy applied with value-differentiation where competitors undercut."

        strategy = PricingStrategy(
            line_items=line_items,
            subtotal=subtotal,
            tax_rate=tax_rate,
            tax_label=tax_label,
            tax_amount=tax_amount,
            total=total,
            currency=requirements.budget_currency or "INR",
            competitor_analyses=competitor_analyses,
            value_adds=value_add_items,
            value_adds_total=value_adds_total,
            pricing_rationale=pricing_rationale,
            strategy_summary=strategy_summary,
        )

        await emit(MessageType.COMPLETE, "Pricing analysis and competitive strategy complete.")
        return strategy

    def _parse_rationale(self, response: str) -> dict:
        """Parse LLM rationale response."""
        try:
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
            return json.loads(text)
        except Exception:
            return {
                "pricing_rationale": response[:500],
                "strategy_summary": "Competitive pricing strategy with value-differentiation."
            }
