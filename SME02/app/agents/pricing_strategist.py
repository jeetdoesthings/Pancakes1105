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
4. Why the customer should choose us over cheaper competitors

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
        self.internal_pricing = self._load_json("internal_pricing.json")
        self.competitor_data = self._load_json("competitor_data.json")
        self.value_adds_catalog = self._load_json("value_adds.json")
        self.tax_data = self._load_json("tax_rates.json")

    def _load_json(self, filename: str) -> dict:
        filepath = os.path.join(settings.DATA_DIR, filename)
        with open(filepath, "r") as f:
            return json.load(f)

    def _find_product(self, item_name: str) -> Optional[dict]:
        """Match a scope item to our internal product catalog."""
        item_lower = item_name.lower()
        for product in self.internal_pricing.get("products", []):
            product_lower = product["name"].lower()
            product_id_lower = product["id"].lower()
            # Match by name keywords or ID
            if (product_id_lower in item_lower.replace(" ", "_") or
                any(kw in item_lower for kw in product_lower.split()[:3]) or
                any(kw in product_lower for kw in item_lower.split()[:3])):
                return product
        return None

    def _find_competitor_prices(self, product_id: str) -> list[dict]:
        """Find competitor prices for a given product."""
        results = []
        for competitor in self.competitor_data.get("competitors", []):
            for offering in competitor.get("offerings", []):
                if offering["product_id"] == product_id:
                    results.append({
                        "competitor_name": competitor["name"],
                        "price": offering["price"],
                        "currency": offering["currency"],
                        "value_adds": offering.get("value_adds", [])
                    })
        return results

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

        # Process each scope item
        for scope_item in requirements.scope_items:
            await emit(MessageType.ACTION, f"Analyzing pricing for: {scope_item.item_name} (Qty: {scope_item.quantity})...")

            # Match to internal catalog
            product = self._find_product(scope_item.item_name)

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

                # Competitor analysis
                comp_prices = self._find_competitor_prices(product["id"])
                for comp in comp_prices:
                    price_diff = unit_price - comp["price"]
                    price_diff_pct = (price_diff / unit_price) * 100 if unit_price > 0 else 0
                    can_match = comp["price"] >= base_cost * (1 + product["min_margin_percent"])

                    analysis = CompetitorAnalysis(
                        competitor_name=comp["competitor_name"],
                        product_id=product["id"],
                        competitor_price=comp["price"],
                        our_price=unit_price,
                        price_difference=price_diff,
                        price_difference_pct=price_diff_pct,
                        can_match=can_match,
                        recommendation="",
                        value_adds_suggested=[]
                    )

                    if comp["price"] < base_cost:
                        # VALUE-DIFFERENTIATION PIVOT!
                        value_differentiation_triggered = True
                        await emit(MessageType.THINKING,
                            f"⚠️ CRITICAL: {comp['competitor_name']} is offering {product['name']} "
                            f"at ₹{comp['price']:,.0f} — BELOW our base cost of ₹{base_cost:,.0f}! "
                            f"Direct price match would be UNPROFITABLE."
                        )
                        await emit(MessageType.ACTION,
                            f"🔄 Initiating VALUE-DIFFERENTIATION PIVOT: Instead of matching the "
                            f"unprofitable price, recommending strategic value-adds to enhance "
                            f"our proposal's competitiveness..."
                        )

                        # Select appropriate value-adds
                        suggested_adds = self._select_value_adds(product["category"])
                        analysis.recommendation = (
                            f"DO NOT price match. Competitor price ₹{comp['price']:,.0f} is below "
                            f"our base cost ₹{base_cost:,.0f}. Pivoting to value-differentiation strategy."
                        )
                        analysis.value_adds_suggested = [va["name"] for va in suggested_adds]

                        for va in suggested_adds:
                            if not any(v.item_name == va["name"] for v in value_add_items):
                                value_add_items.append(LineItem(
                                    item_name=va["name"],
                                    description=va["description"],
                                    quantity=1,
                                    unit_price=0,  # Free value-add
                                    total_price=0,
                                    is_value_add=True,
                                ))
                                await emit(MessageType.RESULT,
                                    f"✅ Value-Add Recommended: {va['name']} — {va['description']} "
                                    f"(included at NO additional cost to differentiate our proposal)"
                                )
                    elif not can_match:
                        await emit(MessageType.THINKING,
                            f"{comp['competitor_name']} offers {product['name']} at ₹{comp['price']:,.0f} "
                            f"(₹{abs(price_diff):,.0f} {'cheaper' if price_diff > 0 else 'more expensive'}). "
                            f"Price match doesn't meet minimum margin of {product['min_margin_percent']*100:.0f}%."
                        )
                        analysis.recommendation = (
                            f"Cannot match competitor price while maintaining minimum margin. "
                            f"Recommend maintaining standard pricing with emphasis on quality and support."
                        )
                    else:
                        await emit(MessageType.RESULT,
                            f"Our price for {product['name']} (₹{unit_price:,.0f}) is competitive "
                            f"vs {comp['competitor_name']} (₹{comp['price']:,.0f}). Maintaining standard pricing."
                        )
                        analysis.recommendation = "Price is competitive. Maintain standard pricing."

                    competitor_analyses.append(analysis)
                    analysis_details.append(
                        f"{product['name']} vs {comp['competitor_name']}: "
                        f"Our ₹{unit_price:,.0f} vs Their ₹{comp['price']:,.0f} — {analysis.recommendation}"
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
        tax_rate = self.tax_data.get("tax_rates", {}).get(
            self.tax_data.get("default_region", "IN"), {}
        ).get("rate", 0.18)
        tax_amount = subtotal * tax_rate
        total = subtotal + tax_amount

        await emit(MessageType.RESULT,
            f"Pricing Summary:\n"
            f"• Subtotal: ₹{subtotal:,.0f}\n"
            f"• GST ({tax_rate*100:.0f}%): ₹{tax_amount:,.0f}\n"
            f"• Total: ₹{total:,.0f}\n"
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
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            total=total,
            currency=requirements.budget_currency or "INR",
            competitor_analyses=competitor_analyses,
            value_adds=value_add_items,
            pricing_rationale=pricing_rationale,
            strategy_summary=strategy_summary,
        )

        await emit(MessageType.COMPLETE, "Pricing analysis and competitive strategy complete.")
        return strategy

    def _select_value_adds(self, category: str) -> list[dict]:
        """Select appropriate value-adds based on product category."""
        all_adds = self.value_adds_catalog.get("value_adds", [])
        # Always include some universal value-adds
        selected = []
        for va in all_adds:
            if va["category"] == category or va["category"] == "service":
                selected.append(va)
                if len(selected) >= 3:
                    break
        if not selected:
            selected = all_adds[:2]
        return selected

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
