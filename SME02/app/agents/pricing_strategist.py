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
    get_currency_conversion_tool,
    get_tax_rate_tool,
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
        additional_instructions: str = ""
    ) -> PricingStrategy:
        """Perform pricing analysis with value-differentiation."""

        async def emit(msg_type: MessageType, content: str):
            if emit_message:
                await emit_message(AgentMessage(
                    agent=self.role,
                    message_type=msg_type,
                    content=content
                ))

        await emit(MessageType.STATUS, "Starting competitive pricing analysis...")
        await emit(MessageType.THINKING, f"Analyzing {len(requirements.scope_items)} scope items against internal pricing catalog and competitor data...")

        line_items = []
        value_add_items = []
        competitor_analyses = []
        analysis_details = []
        value_differentiation_triggered = False

        # 1. Parse currency override from additional_instructions
        target_curr = requirements.target_currency if requirements.target_currency else "INR"
        
        # Simple heuristic for currency override in instructions
        instr_lower = additional_instructions.lower()
        currency_map = {
            "usd": "USD", "dollar": "USD", "$": "USD",
            "eur": "EUR", "euro": "EUR", "€": "EUR",
            "gbp": "GBP", "pound": "GBP", "£": "GBP",
            "aed": "AED", "dirham": "AED",
            "sgd": "SGD", "singapore": "SGD",
            "inr": "INR", "rupee": "INR", "₹": "INR"
        }
        for kw, code in currency_map.items():
            if kw in instr_lower:
                target_curr = code
                await emit(MessageType.STATUS, f"Detected currency override in instructions: {target_curr}")
                break

        currency_rate = 1.0
        currency_symbol = self.tax_data.get("currency_symbols", {}).get(target_curr, target_curr if target_curr != "INR" else "₹")
        
        if target_curr != "INR":
            await emit(MessageType.THINKING, f"Target currency is {target_curr}. Looking up REAL-TIME exchange rate...")
            conv_resp = get_currency_conversion_tool.invoke({"base_currency": "INR", "target_currency": target_curr})
            await emit(MessageType.ACTION, f"Currency Conversion: {conv_resp}")
            
            import re
            # Match "Rate: 0.0123" or "REAL-TIME Rate: ... = 0.0123"
            match = re.search(r"(?:Rate:|REAL-TIME Rate:.*?=)\s*([\d.]+)", conv_resp)
            if match:
                currency_rate = float(match.group(1))
            else:
                # Fallback: check if the response contains raw numbers
                numbers = re.findall(r"[\d.]+", conv_resp)
                if len(numbers) >= 1:
                    currency_rate = float(numbers[-1]) # Usually the target rate is the last one mentioned

        # 2. Get tax details
        tax_info_str = get_tax_rate_tool.invoke(requirements.client_country_code)
        try:
            tax_info = json.loads(tax_info_str)
        except Exception:
            tax_info = {"name": "Tax", "rate": 0.18}
        tax_name = tax_info.get("name", "Tax")
        tax_rate = tax_info.get("rate", 0.18)

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
                base_cost = product["base_cost"] * currency_rate
                unit_price = product["standard_price"] * currency_rate
                total_price = unit_price * scope_item.quantity

                await emit(MessageType.THINKING,
                    f"Matched '{scope_item.item_name}' to internal product '{product['name']}' "
                    f"(Base Cost: {currency_symbol}{base_cost:,.2f}, Standard Price: {currency_symbol}{unit_price:,.2f})"
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
                    if "BENCHMARKS_EXIST" in comp_tool_response:
                        market_research_context = comp_tool_response.replace("BENCHMARKS_EXIST:", "Local Benchmarks:").strip()
                        # Optional live search to augment
                        search_query = f"cost of {product['name']} in India"
                        await emit(MessageType.ACTION, f"Found local benchmarks for {product['name']}. Attempting to augment with live search...")
                        live_res = research_market_rates_tool.invoke(search_query)
                        if live_res:
                            market_research_context += "\n" + live_res
                    else:
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

                comp_prices_floats = [c["price"] * currency_rate for c in comp_prices]
                
                # Deterministic pricing algorithm (MATCH / PIVOT / BASELINE)
                final_price, strategy_type, rationale = compute_price(
                    cost=base_cost,
                    competitor_prices=comp_prices_floats,
                    margin=product["min_margin_percent"],
                    budget=(requirements.budget_amount * currency_rate) if requirements.budget_amount > 0 else None,
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

                analysis = CompetitorAnalysis(
                    competitor_name=display_comp_name,
                    product_id=product["id"],
                    competitor_price=lowest_comp,
                    our_price=final_price,
                    price_difference=final_price - lowest_comp,
                    price_difference_pct=((final_price - lowest_comp) / final_price) * 100 if final_price > 0 else 0,
                    can_match=can_match,
                    recommendation=rationale
                )

                # ── Deterministic Value-Add Trigger (Aggressive) ──
                # Trigger if PIVOT (loss of margin), MARGIN_DEFENSE (protecting margin) 
                # or if our final price is simply higher than the lowest competitor.
                is_expensive = (lowest_comp > 0 and final_price > lowest_comp)
                
                if strategy_type in ["PIVOT", "MARGIN_DEFENSE"] or is_expensive:
                    value_differentiation_triggered = True
                    await emit(MessageType.THINKING,
                        f"✨ Strategic differentiation triggered: Price {currency_symbol}{final_price:,.2f} is higher than "
                        f"competitor {currency_symbol}{lowest_comp:,.2f}. Adding value-add bundles."
                    )
                    
                    # Select appropriate value-adds via Tool
                    va_tool_resp = suggest_value_add_tool.invoke(product["category"])
                    suggested_adds = []
                    if not va_tool_resp.startswith("No "):
                        try:
                            # Strip thinking blocks if the LLM-based tool returned any
                            clean_json = re.sub(r"<think>.*?</think>", "", va_tool_resp, flags=re.DOTALL).strip()
                            suggested_adds = json.loads(clean_json)
                        except Exception:
                            pass
                            
                    analysis.recommendation += " Adding value-add bundles to compensate."
                    for va in suggested_adds:
                        analysis.value_adds_suggested.append(va["name"])
                        value_add_items.append(LineItem(
                            item_name=va["name"],
                            description=va["description"],
                            quantity=1,
                            unit_price=0.0,
                            total_price=0.0,
                            is_value_add=True
                        ))
                elif strategy_type == "MARGIN_DEFENSE":
                    await emit(MessageType.THINKING, f"🛡️ MARGIN_DEFENSE strategy: Defending profit margin against low competitor {currency_symbol}{lowest_comp:,.2f}.")
                elif strategy_type == "BASELINE":
                    if market_research_context:
                        await emit(MessageType.THINKING,
                            f"Using Market Research for '{product['name']}'"
                        )
                        analysis.recommendation = "Pricing accurately aligned with competitive local market benchmarks."
                    else:
                        await emit(MessageType.THINKING,
                            f"No competitor data for '{product['name']}'. Using BASELINE pricing at target margin."
                        )
                else:
                    await emit(MessageType.THINKING, f"✅ MATCH strategy: Best competitor {currency_symbol}{lowest_comp:,.2f}, our price {currency_symbol}{final_price:,.2f}.")
                    
                competitor_analyses.append(analysis)
                
                comp_display_name = analysis.competitor_name
                if comp_display_name == "None" and market_research_context:
                    comp_display_name = "Market Benchmarks"
                
                analysis_details.append(
                    f"{product['name']} vs {comp_display_name}: "
                    f"Our {currency_symbol}{unit_price:,.2f} vs Their {((currency_symbol)+format(lowest_comp, ',.2f')) if lowest_comp > 0 else 'Unknown'} — {market_research_context if market_research_context else analysis.recommendation}"
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

        # Calculate totals
        subtotal = sum(item.total_price for item in line_items)
        tax_amount = subtotal * tax_rate
        total = subtotal + tax_amount

        await emit(MessageType.RESULT,
            f"Pricing Summary:\n"
            f"• Subtotal: {currency_symbol}{subtotal:,.2f}\n"
            f"• {tax_name} ({tax_rate*100:.0f}%): {currency_symbol}{tax_amount:,.2f}\n"
            f"• Total: {currency_symbol}{total:,.2f}\n"
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
            prompt_text = STRATEGY_PROMPT.format(
                requirements_json=json.dumps(requirements.model_dump(), indent=2, default=str),
                internal_pricing_json=json.dumps(self.internal_pricing, indent=2),
                competitor_json=json.dumps(self.competitor_data, indent=2),
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
            tax_name=tax_name,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            total=total,
            currency=target_curr,
            currency_symbol=currency_symbol,
            competitor_analyses=competitor_analyses,
            value_adds=value_add_items,
            pricing_rationale=pricing_rationale,
            strategy_summary=strategy_summary,
            is_pivot_strategy=value_differentiation_triggered
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
