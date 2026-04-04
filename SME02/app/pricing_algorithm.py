"""
Pricing Algorithm (Deterministic)
==================================
Pure-function pricing engine implementing MATCH / PIVOT / BASELINE strategies.

All pricing decisions are rule-based and fully explainable.
No LLM involvement — the algorithm is the single source of truth.

Design Principle: Deterministic over Generative (Section 7.2)
"""

from typing import List, Tuple, Optional


def compute_price(
    cost: float,
    competitor_prices: List[float],
    margin: float = 0.30,
    epsilon: float = 0.01,
    budget: Optional[float] = None,
    urgency_multiplier: float = 1.0,
) -> Tuple[float, str, str]:
    """
    Computes the final price using deterministic MATCH / PIVOT / BASELINE logic.

    Args:
        cost:                 Our internal base cost for one unit.
        competitor_prices:    List of competitor prices for the same product.
        margin:               Target profit margin (e.g. 0.30 = 30%).
        epsilon:              Small undercut delta when matching competitors.
        budget:               Client's stated budget (if known). Used to cap price.
        urgency_multiplier:   Scalar ≥1.0 for rush/premium delivery (default 1.0 = normal).

    Returns:
        Tuple of (final_price, strategy_name, rationale_string).
    """
    if cost <= 0:
        return 0.0, "ERROR", "Invalid base cost (≤0)."

    # 1. Compute baseline target price
    target_price = cost * (1 + margin) * urgency_multiplier

    # 2. Determine strategy
    if not competitor_prices:
        # ── BASELINE: no competitive intelligence available ──
        final_price = target_price
        strategy = "BASELINE"
        rationale = (
            f"No competitor data available. Applying baseline pricing at "
            f"{margin*100:.0f}% target margin."
        )
    else:
        min_comp = min(competitor_prices)

        if min_comp > cost:
            # ── MATCH: undercut competitor while defending margin ──
            if target_price < min_comp - epsilon:
                final_price = min_comp - epsilon
                strategy = "MATCH"
                rationale = (
                    f"Successfully undercutting lowest competitor ({min_comp:,.2f}) while maintaining "
                    f"beyond {margin*100:.0f}% minimum margin."
                )
            else:
                final_price = target_price
                strategy = "MARGIN_DEFENSE"
                rationale = (
                    f"Lowest competitor ({min_comp:,.2f}) is below our target margin. "
                    f"Defending {margin*100:.0f}% minimum margin (at {target_price:,.2f}), "
                    f"pivoting to value-differentiation."
                )
        else:
            # ── PIVOT: competitor below our cost — value differentiation ──
            final_price = target_price
            strategy = "PIVOT"
            rationale = (
                f"Competitor price ({min_comp:,.2f}) is at or below our cost "
                f"({cost:,.2f}). Preserving margin, pivoting to value-add bundles."
            )

    # 3. Dynamic adjustment: budget cap
    if budget and budget > 0 and final_price > budget:
        # Respect client budget if it still covers cost (no loss-leader)
        if budget >= cost:
            original = final_price
            final_price = budget
            rationale += (
                f" Price capped to client budget ({budget:,.2f}) "
                f"from original {original:,.2f}."
            )
        else:
            rationale += (
                f" Client budget ({budget:,.2f}) is below our cost; "
                f"maintaining target price."
            )

    return round(final_price, 2), strategy, rationale
