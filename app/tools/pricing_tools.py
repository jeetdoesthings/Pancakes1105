import json
import os
from typing import List, Dict, Any
from langchain_core.tools import tool
from app.config import settings

def _load_json(filename: str) -> dict:
    filepath = os.path.join(settings.DATA_DIR, filename)
    with open(filepath, "r") as f:
        return json.load(f)

@tool
def get_internal_pricing_tool(product_id_or_keyword: str) -> str:
    """Queries the internal product catalog for cost and standard pricing for a given product_id or keyword.
    Use this to find how much our product costs to deliver and our standard retail price.
    Returns JSON of matched products.
    """
    data = _load_json("internal_pricing.json")
    query = product_id_or_keyword.lower()
    matches = []
    for p in data.get("products", []):
        if query in p["id"].lower() or query in p["name"].lower():
            matches.append(p)
    if matches:
        return json.dumps(matches, indent=2)
    return f"No internal pricing found matching '{product_id_or_keyword}'."

@tool
def get_competitor_data_tool(product_id: str) -> str:
    """Queries local competitor intelligence to find what competitors are charging for an exact product_id.
    If this returns no data, you SHOULD use the research_market_rates_tool to find dynamic market data.
    """
    data = _load_json("competitor_data.json")
    results = []

    # Check old structure (competitors array)
    for comp in data.get("competitors", []):
        for off in comp.get("offerings", []):
            if off["product_id"] == product_id:
                results.append({
                    "competitor": comp["name"],
                    "price": off["price"],
                    "currency": off["currency"],
                    "value_adds": off.get("value_adds", [])
                })

    if results:
        return json.dumps(results, indent=2)

    # Check new structure (benchmarking) — return a clean summary, not raw JSON
    benchmarks = data.get("competitor_benchmarking", {})
    if benchmarks:
        parts = []
        for key, val in benchmarks.items():
            readable_key = key.replace("_", " ").title()
            parts.append(f"{readable_key}: {val}")
        return "Market Benchmarks: " + "; ".join(parts)

    return f"No competitor data found for product_id: '{product_id}'. Use research_market_rates_tool for dynamic info."

@tool
def research_market_rates_tool(query: str) -> str:
    """Performs a live web search to find current market rates, competitor prices, or benchmarking for a service or product.
    Use this when local 'competitor_data.json' is missing information for an RFP item.
    Example query: 'market rate for GIS property survey per unit in India 2024'
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "" # Silently fail if not installed to avoid cluttering rationale
        
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3, region='in-en'))
            if results:
                # Filter out likely irrelevant/chinese fallback results by checking ascii or simple heuristics if needed,
                # but adding region='in-en' usually fixes it.
                formatted = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
                return f"Live Market Research Results for '{query}':\n{formatted}"
    except Exception as e:
        pass
    return ""

@tool
def suggest_value_add_tool(category: str) -> str:
    """Returns a deterministic list of strategic value-adds to offer for a specific product category (e.g., 'hardware', 'software', 'service').
    Use this when a competitor's price is LOWER than our base cost, so we must pivot to value-differentiation instead of a price match.
    """
    data = _load_json("value_adds.json")
    all_adds = data.get("value_adds", [])
    selected = []
    for va in all_adds:
        if va["category"] == category or va["category"] == "service":
            selected.append(va)
            if len(selected) >= 2:
                break
    if not selected:
        selected = all_adds[:2]
    return json.dumps(selected, indent=2)

@tool
def calculate_profit_margin_tool(cost: float, price: float) -> str:
    """Calculates the profit margin percentage deterministically.
    Always use this to verify if matching a competitor's price maintains a positive margin over our base cost.
    """
    if price <= 0:
        return "Margin is 0% (divide by zero avoided for 0 price)."
    margin = ((price - cost) / price) * 100
    return f"Margin is {margin:.2f}%"
