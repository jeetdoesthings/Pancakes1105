import pytest
from app.pricing_algorithm import compute_price

def test_match_strategy_undercuts_competitor():
    """MATCH: competitor above cost, we undercut while defending margin."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[140.0, 150.0], margin=0.30, epsilon=1.0
    )
    assert strategy == "MATCH"
    # target=130, minComp=140, max(130, 140-1)=139
    assert price == 139.0

def test_match_strategy_hits_floor():
    """MATCH: undercutting would drop below target, so floor applies."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[130.5, 150.0], margin=0.30, epsilon=1.0
    )
    assert strategy == "MATCH"
    # target=130, max(130, 130.5-1)=max(130,129.5)=130
    assert price == 130.0

def test_pivot_strategy():
    """PIVOT: competitor below our cost — value differentiation."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[90.0], margin=0.30, epsilon=1.0
    )
    assert strategy == "PIVOT"
    assert price == 130.0

def test_baseline_no_competitors():
    """BASELINE: no competitor data available at all."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[], margin=0.30
    )
    assert strategy == "BASELINE"
    assert price == 130.0

def test_budget_cap():
    """Dynamic adjustment: price capped to client budget."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[200.0], margin=0.30, budget=125.0
    )
    # target=130, but budget=125 and 125>=cost, so capped
    assert price == 125.0
    assert "capped" in rationale.lower()

def test_budget_below_cost_ignored():
    """Budget below cost should NOT cap price (no loss-leader)."""
    price, strategy, rationale = compute_price(
        cost=100.0, competitor_prices=[200.0], margin=0.30, budget=80.0
    )
    # Budget 80 < cost 100 — ignore cap, maintain target
    assert price >= 130.0

def test_urgency_multiplier():
    """Rush delivery should increase price."""
    normal_price, _, _ = compute_price(cost=100.0, competitor_prices=[], margin=0.30)
    rush_price, _, _ = compute_price(
        cost=100.0, competitor_prices=[], margin=0.30, urgency_multiplier=1.2
    )
    assert rush_price > normal_price

def test_zero_cost_error():
    """Zero cost should return ERROR strategy."""
    price, strategy, _ = compute_price(cost=0.0, competitor_prices=[50.0])
    assert strategy == "ERROR"
    assert price == 0.0
