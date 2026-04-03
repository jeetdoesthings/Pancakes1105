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
    """Queries competitor intelligence to find what competitors are charging for an exact product_id.
    Use this to perform competitive pricing analysis and see if our standard price is competitive.
    """
    data = _load_json("competitor_data.json")
    results = []
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
    return f"No competitor data found for product_id: '{product_id}'."

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
