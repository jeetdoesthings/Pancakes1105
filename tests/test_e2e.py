"""
End-to-End Test: HB Grade Pencil RFP
=====================================
Tests:
  - International client (USD currency → Twist 1)
  - Stationery category (pencil retrieval → Criticism 3)
  - PDF generation without errors
  - UniversalRFP schema population
  - Similar RFP retrieval
"""

import urllib.request
import json
import time
import sys
import os

BASE = "http://localhost:8000"

def api(path, data=None, method="GET"):
    """Helper to call the API."""
    url = f"{BASE}{path}"
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    else:
        req = urllib.request.Request(url, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        print(f"  ✗ API Error: {e}")
        return None

def stream_sse(path, timeout=120):
    """Stream SSE events and return the last job_state message."""
    url = f"{BASE}{path}"
    last_state = None
    messages = []
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        while True:
            line = resp.readline().decode("utf-8")
            if not line:
                break
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "job_state":
                    last_state = data
                    break
                else:
                    messages.append(data)
    except Exception as e:
        print(f"  ⚠ SSE stream ended: {e}")
    return last_state, messages

def main():
    print("=" * 60)
    print("SME02 End-to-End Test: HB Grade Pencil RFP")
    print("=" * 60)

    # ── Step 1: Submit RFP ──
    print("\n[1/6] Submitting RFP...")
    rfp_text = (
        "Request for Proposal: Supply of HB Grade Pencils\n"
        "Client: Johnson and Associates, New York, USA\n"
        "Quantity: 500 units\n"
        "Budget: $2,000 USD\n"
        "Deadline: 2026-05-01\n"
        "Requirements: Standard HB pencils, hexagonal barrel, "
        "eraser tip. Delivery to Mumbai warehouse."
    )
    result = api("/api/process-rfp", {
        "rfp_text": rfp_text,
        "company_name": "Ering Solutions",
        "contact_name": "Sales Team",
        "contact_email": "sales@eringsolutions.com",
        "contact_phone": "+91-9876543210",
    })
    if not result:
        print("  ✗ FAILED to submit RFP")
        sys.exit(1)
    job_id = result["job_id"]
    print(f"  ✓ Job created: {job_id}")

    # ── Step 2: Stream processing ──
    print(f"\n[2/6] Streaming agent processing (may take 30-60s)...")
    last_state, messages = stream_sse(f"/api/stream/{job_id}", timeout=180)

    if not last_state:
        print("  ✗ FAILED — no final state received")
        sys.exit(1)

    job_status = last_state.get("job_status", "unknown")
    print(f"  ✓ Processing complete — status: {job_status}")

    # ── Step 3: Check UniversalRFP ──
    print(f"\n[3/6] Checking UniversalRFP schema...")
    universal_rfp = last_state.get("universal_rfp")
    if universal_rfp:
        print(f"  ✓ UniversalRFP populated:")
        print(f"    rfpId: {universal_rfp.get('rfpId')}")
        print(f"    title: {universal_rfp.get('title')}")
        print(f"    productName: {universal_rfp.get('productName')}")
        print(f"    category: {universal_rfp.get('category')}")
        print(f"    currency: {universal_rfp.get('currency')}")
        print(f"    budget: {universal_rfp.get('budget')}")
        print(f"    quantity: {universal_rfp.get('quantity')}")
    else:
        print("  ✗ UniversalRFP not found in response")

    # ── Step 4: Check Similar RFPs ──
    print(f"\n[4/6] Checking Similar RFP retrieval...")
    similar_rfps = last_state.get("similar_rfps", [])
    if similar_rfps:
        print(f"  ✓ Found {len(similar_rfps)} similar RFPs:")
        for i, sr in enumerate(similar_rfps):
            rfp = sr.get("rfp", {})
            print(f"    [{i+1}] {rfp.get('title', 'N/A')} (score: {sr.get('combined_score', 0):.2f})")
            print(f"        Product: {rfp.get('productName', 'N/A')} | Budget: {rfp.get('currency', '')} {rfp.get('budget', 'N/A')}")
    else:
        print("  ⚠ No similar RFPs found (may be expected if DB is empty)")

    # ── Step 5: Check Pricing Strategy ──
    print(f"\n[5/6] Checking Pricing Strategy...")
    pricing = last_state.get("pricing_strategy")
    if pricing:
        print(f"  ✓ Pricing strategy populated:")
        print(f"    Currency: {pricing.get('currency')}")
        print(f"    Subtotal: {pricing.get('subtotal')}")
        print(f"    Total: {pricing.get('total')}")
        print(f"    Line items: {len(pricing.get('line_items', []))}")
        print(f"    Value adds: {len(pricing.get('value_adds', []))}")
        print(f"    Competitor analyses: {len(pricing.get('competitor_analyses', []))}")

        # Check algorithm decision log fields
        for ca in pricing.get("competitor_analyses", []):
            strategy = ca.get("algorithm_strategy", "")
            if strategy:
                print(f"    Algorithm Decision for {ca.get('competitor_name')}: {strategy}")
                print(f"      Input cost: {ca.get('algorithm_input_cost')}")
                print(f"      Output price: {ca.get('algorithm_output_price')}")
                print(f"      Threshold: {ca.get('algorithm_threshold')}")
    else:
        print("  ✗ Pricing strategy not found")

    # ── Step 6: Approve and generate PDF ──
    print(f"\n[6/6] Approving proposal and generating PDF...")
    last_state2, _ = stream_sse(f"/api/approve/{job_id}", timeout=120)

    if not last_state2:
        print("  ✗ FAILED — no response from approval")
        sys.exit(1)

    pdf_ready = last_state2.get("pdf_ready", False)
    final_status = last_state2.get("job_status", "unknown")
    print(f"  ✓ PDF generation complete — status: {final_status}, pdf_ready: {pdf_ready}")

    if pdf_ready:
        # Download PDF
        print(f"\n  Downloading PDF...")
        try:
            req = urllib.request.Request(f"{BASE}/api/download-pdf/{job_id}")
            resp = urllib.request.urlopen(req, timeout=15)
            pdf_bytes = resp.read()
            pdf_size = len(pdf_bytes)
            print(f"  ✓ PDF downloaded: {pdf_size:,} bytes ({pdf_size/1024:.1f} KB)")

            # Save to output dir
            output_path = os.path.join("output", f"test_e2e_{job_id}.pdf")
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)
            print(f"  ✓ PDF saved to: {output_path}")
        except Exception as e:
            print(f"  ✗ PDF download failed: {e}")
    else:
        print("  ✗ PDF was not generated")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    checks = [
        ("RFP submitted", bool(job_id)),
        ("Processing completed", job_status in ("awaiting_approval", "completed")),
        ("UniversalRFP populated", bool(universal_rfp)),
        ("Similar RFPs retrieved", len(similar_rfps) > 0),
        ("Pricing strategy generated", bool(pricing)),
        ("Algorithm decisions logged", any(
            ca.get("algorithm_strategy") for ca in (pricing or {}).get("competitor_analyses", [])
        )),
        ("PDF generated", pdf_ready),
    ]
    for name, passed in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")

    passed_count = sum(1 for _, p in checks if p)
    print(f"\n  Result: {passed_count}/{len(checks)} checks passed")
    print("=" * 60)

if __name__ == "__main__":
    main()
