"""
Seed Historical RFPs for Similarity Retrieval
==============================================
Populates the SQLite database and ChromaDB similarity collection
with representative historical RFPs so judges can see the retrieval
system in action.

Covers: stationery/pencils, IT hardware, GIS services, software development,
networking equipment, and training services.
"""

import sys
import os
import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.rfp_schema import UniversalRFP
from app.db import insert_rfp, init_db
from app.services.rfp_similarity import rfp_similarity_service


HISTORICAL_RFPS = [
    # ── Stationery / Writing Instruments (for pencil example) ──
    UniversalRFP(
        rfpId="hist-stationery-001",
        title="Office Stationery Supply Contract 2025",
        productName="Pencil HB Grade",
        category="stationery",
        quantity=1000,
        unit="box",
        deadline=datetime.date(2025, 6, 15),
        budget=50000.0,
        currency="INR",
        taxRate=0.18,
        location="Mumbai, India",
        description="Supply of 1000 boxes of HB grade pencils for government schools in Mumbai district. Must meet IS 1986 standards. Delivery in quarterly batches.",
    ),
    UniversalRFP(
        rfpId="hist-stationery-002",
        title="School Writing Instruments Procurement",
        productName="Ballpoint Pens and Pencils",
        category="stationery",
        quantity=5000,
        unit="set",
        deadline=datetime.date(2025, 3, 1),
        budget=120000.0,
        currency="INR",
        taxRate=0.18,
        location="Delhi, India",
        description="Procurement of writing instruments including ballpoint pens, mechanical pencils, and erasers for 50 government schools. Annual supply contract with quality certification required.",
    ),
    UniversalRFP(
        rfpId="hist-stationery-003",
        title="Educational Supplies - Writing and Drawing Materials",
        productName="Drawing Pencils and Art Supplies",
        category="stationery",
        quantity=300,
        unit="kit",
        deadline=datetime.date(2025, 8, 20),
        budget=75000.0,
        currency="INR",
        taxRate=0.18,
        location="Pune, India",
        description="Art and drawing pencil sets for vocational training centers. Includes graphite pencils (2H to 8B), charcoal pencils, and erasers. ISO 9001 certified vendors preferred.",
    ),

    # ── IT Hardware ──
    UniversalRFP(
        rfpId="hist-it-hardware-001",
        title="Server Infrastructure Upgrade for Municipal Office",
        productName="Dell PowerEdge R760 Server",
        category="hardware",
        quantity=5,
        unit="each",
        deadline=datetime.date(2025, 9, 30),
        budget=5000000.0,
        currency="INR",
        taxRate=0.18,
        location="Bangalore, India",
        description="Supply and installation of 5 rack-mounted servers with 512GB RAM, NVMe SSDs, and redundant power supplies. Includes rack setup, cabling, and 3-year warranty.",
    ),
    UniversalRFP(
        rfpId="hist-it-hardware-002",
        title="Network Equipment Procurement - Campus LAN",
        productName="Cisco Catalyst Switches",
        category="hardware",
        quantity=12,
        unit="each",
        deadline=datetime.date(2025, 11, 15),
        budget=3500000.0,
        currency="INR",
        taxRate=0.18,
        location="Hyderabad, India",
        description="Core and access switches for campus LAN upgrade. 2x Catalyst 9300 core switches, 10x Catalyst 9200 access switches. Includes configuration and 1-year support.",
    ),

    # ── GIS / Survey Services ──
    UniversalRFP(
        rfpId="hist-gis-001",
        title="GIS-Based Property Tax Mapping - Nagpur Municipal Corp",
        productName="GIS Application Development",
        category="service",
        quantity=1,
        unit="service",
        deadline=datetime.date(2025, 12, 31),
        budget=4880000.0,
        currency="INR",
        taxRate=0.18,
        location="Nagpur, India",
        description="Door-to-door property survey, GIS base map enhancement, UAV/LiDAR survey, digitization of existing maps, GIS application development, cloud hosting, and staff training for property tax mapping.",
    ),
    UniversalRFP(
        rfpId="hist-gis-002",
        title="Urban GIS Master Plan - Smart City Initiative",
        productName="GIS Master Plan Preparation",
        category="service",
        quantity=1,
        unit="service",
        deadline=datetime.date(2026, 3, 31),
        budget=6200000.0,
        currency="INR",
        taxRate=0.18,
        location="Indore, India",
        description="Comprehensive GIS-based urban master plan including field survey, satellite imagery analysis, stakeholder workshops, and final master plan document with digital deliverables.",
    ),

    # ── Software Development ──
    UniversalRFP(
        rfpId="hist-software-001",
        title="Custom ERP Development for Manufacturing Unit",
        productName="ERP Software Development",
        category="software",
        quantity=1,
        unit="service",
        deadline=datetime.date(2026, 1, 15),
        budget=8500000.0,
        currency="INR",
        taxRate=0.18,
        location="Chennai, India",
        description="End-to-end ERP system including inventory management, production planning, HR module, and financial reporting. Cloud-hosted with mobile app access.",
    ),

    # ── Training Services ──
    UniversalRFP(
        rfpId="hist-training-001",
        title="IT Staff Capacity Building Program",
        productName="Technical Training Workshops",
        category="service",
        quantity=200,
        unit="person-days",
        deadline=datetime.date(2026, 5, 1),
        budget=1500000.0,
        currency="INR",
        taxRate=0.18,
        location="Kolkata, India",
        description="Training program for 200 government IT staff covering cloud computing, cybersecurity, data analytics, and GIS fundamentals. Certification upon completion required.",
    ),
]


def seed():
    """Insert all historical RFPs into the database and vector store."""
    init_db()

    print(f"Seeding {len(HISTORICAL_RFPS)} historical RFPs...")

    for rfp in HISTORICAL_RFPS:
        try:
            insert_rfp(rfp)
            rfp_similarity_service.index_rfp(rfp)
            print(f"  ✓ {rfp.rfpId}: {rfp.title[:60]}")
        except Exception as e:
            # Skip duplicates (rfpId is primary key)
            if "UNIQUE" in str(e) or "duplicate" in str(e).lower():
                print(f"  ⊘ {rfp.rfpId}: already exists")
            else:
                print(f"  ✗ {rfp.rfpId}: {e}")

    print("Seeding complete.")


if __name__ == "__main__":
    seed()
