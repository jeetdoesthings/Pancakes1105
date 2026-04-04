import pytest
import datetime
from app.rfp_schema import UniversalRFP
from app.db import insert_rfp, get_rfp_by_id, init_db
from app.rfp_search import search_rfps

# Use unique IDs so multiple runs don't clash on primary keys
import uuid

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_insert_and_get_rfp():
    rfp_id = str(uuid.uuid4())
    rfp = UniversalRFP(
        rfpId=rfp_id,
        title="School Supplies 2026",
        productName="pencil",
        quantity=5000,
        unit="box",
        deadline=datetime.date(2026, 7, 1),
        budget=1200.0,
        currency="USD",
        taxRate=0.08,
        description="We need 5000 boxes of No. 2 pencils for the upcoming academic year."
    )
    insert_rfp(rfp)
    
    fetched = get_rfp_by_id(rfp_id)
    assert fetched is not None
    assert fetched.rfpId == rfp_id
    assert fetched.productName == "pencil"
    assert fetched.budget == 1200.0

def test_search_rfps_by_product():
    # Insert multiple RFPs
    rfp_id_1 = str(uuid.uuid4())
    insert_rfp(UniversalRFP(
        rfpId=rfp_id_1,
        title="HQ Notebooks",
        productName="notebook",
        quantity=100,
        unit="pkg",
        deadline=datetime.date(2026, 8, 1),
        currency="EUR"
    ))
    
    rfp_id_2 = str(uuid.uuid4())
    insert_rfp(UniversalRFP(
        rfpId=rfp_id_2,
        title="HQ Notebooks Pt 2",
        productName="notebook",
        quantity=200,
        unit="pkg",
        deadline=datetime.date(2026, 9, 1),
        currency="EUR"
    ))
    
    # Exact match filter
    results = search_rfps(product="notebook")
    # Should be at least 2 since we inserted 2
    ids = [r.rfpId for r in results]
    assert rfp_id_1 in ids
    assert rfp_id_2 in ids

def test_search_rfps_fts():
    rfp_id = str(uuid.uuid4())
    insert_rfp(UniversalRFP(
        rfpId=rfp_id,
        title="Advanced Workstation Setup",
        productName="computer",
        quantity=50,
        unit="each",
        deadline=datetime.date(2026, 10, 1),
        currency="USD",
        description="Requires 32GB RAM minimum, OLED displays, and mechanical keyboards."
    ))
    
    # Keyword search
    results = search_rfps(query="OLED")
    
    ids = [r.rfpId for r in results]
    assert rfp_id in ids
