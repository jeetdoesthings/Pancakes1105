import sys
import os
import json

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tools.pricing_tools import get_currency_conversion_tool

def test_currency():
    print("Testing REAL-TIME currency conversion (INR to USD)...")
    res = get_currency_conversion_tool.invoke({"base_currency": "INR", "target_currency": "USD"})
    print(f"Result: {res}")
    
    print("\nTesting fallback/static (INR to JPY)...")
    res = get_currency_conversion_tool.invoke({"base_currency": "INR", "target_currency": "JPY"})
    print(f"Result: {res}")

if __name__ == "__main__":
    test_currency()
