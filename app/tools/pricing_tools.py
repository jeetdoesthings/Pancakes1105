import json
import os
import requests
from functools import lru_cache
from typing import List, Dict, Any
from langchain_core.tools import tool
from app.config import settings

@lru_cache(maxsize=32)
def _load_json(filename: str) -> dict:
    filepath = os.path.join(settings.DATA_DIR, filename)
    if not os.path.exists(filepath):
        return {}
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

@tool
def get_currency_conversion_tool(base_currency: str, target_currency: str) -> str:
    """Gets the conversion rate from base_currency (e.g., INR) to target_currency (e.g., USD).
    Uses real-time data from Frankfurter API with local cache as backup.
    """
    # 1. Try Frankfurter API (Real-time)
    try:
        url = f"https://api.frankfurter.app/latest?from={base_currency}&to={target_currency}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            rate = data.get("rates", {}).get(target_currency)
            if rate:
                return f"REAL-TIME Rate: 1 {base_currency} = {rate:.4f} {target_currency} (Date: {data.get('date')})"
    except Exception:
        pass

    # 2. Try DuckDuckGo (Backup web search)
    query = f"exchange rate {base_currency} to {target_currency}"
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=2))
            if results:
                formatted = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
                return f"Live Exchange Rate Research (Fallback):\n{formatted}"
    except Exception:
        pass

    # 3. Last Resort: Local static data
    data = _load_json("tax_rates.json")
    rates = data.get("currency_rates", {})
    if base_currency == "INR" and target_currency in rates:
        return f"Static Rate: 1 INR = {1 / rates[target_currency]:.4f} {target_currency} (Rate: {rates[target_currency]})"

    return f"Estimate: Assume 1 USD approx 83.5 INR, 1 EUR approx 90.3 INR, 1 GBP approx 105.8 INR."

@tool
def get_tax_rate_tool(country_code: str) -> str:
    """Looks up the appropriate tax rate (e.g., VAT, GST) for a given 2-letter country code (e.g., IN, US, UK).
    Falls back to a live search if the country code is unknown.
    """
    data = _load_json("tax_rates.json")
    rates = data.get("tax_rates", {})

    if country_code in rates:
        return json.dumps(rates[country_code])

    # Live search fallback for unknown countries
    query = f"current VAT or GST tax rate in {country_code} for consulting services"
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            search_res = list(ddgs.text(query, max_results=1))
            if search_res:
                return json.dumps({
                    "name": "Local Tax (Estimated)",
                    "rate": 0.15,
                    "source": search_res[0]['body'][:100]
                })
    except Exception:
        pass

    return json.dumps({
        "name": data.get("default_tax_name", "Tax"),
        "rate": data.get("default_tax_rate", 0.18)
    })
