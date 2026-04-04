"""Generate a sample IGNIS-style quotation PDF for smoke testing."""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.models import (
    CompetitorAnalysis,
    ExtractedRequirements,
    LineItem,
    PricingStrategy,
    ProposalDraft,
    ProposalSection,
    ScopeItem,
)
from app.services.pdf_generator import PDFGenerator


def generate_sample_pdf(job_id: str = "sample-ignis") -> str:
    """Build representative objects and generate a sample quotation PDF."""
    generator = PDFGenerator()

    requirements = ExtractedRequirements(
        project_name="IT Infrastructure Upgrade",
        issuing_company="TechCorp India",
        budget_amount=5000000,
        scope_items=[
            ScopeItem(
                item_name="Server Rack",
                description="42U enterprise-grade rack with cooling and cable management",
                quantity=2,
                category="hardware",
            )
        ],
    )

    pricing = PricingStrategy(
        line_items=[
            LineItem(
                item_name="Server Rack",
                quantity=2,
                unit_price=2500000,
                total_price=5000000,
            )
        ],
        subtotal=5000000,
        total=5900000,
        currency="INR",
        strategy_summary="Pivoting to value differentiation because competitor pricing is below sustainable cost.",
        competitor_analyses=[
            CompetitorAnalysis(
                competitor_name="CheapIT",
                product_id="SR-100",
                competitor_price=1500000,
                our_price=2500000,
                price_difference=1000000,
                price_difference_pct=40.0,
                can_match=False,
                recommendation="Pivot",
            )
        ],
    )

    proposal = ProposalDraft(
        executive_summary="This is a professional proposal for TechCorp.",
        technical_proposal=[ProposalSection(title="Hardware", content="Standard rack setup.")],
    )

    return generator.generate(
        job_id=job_id,
        requirements=requirements,
        pricing=pricing,
        proposal=proposal,
    )


if __name__ == "__main__":
    print("Generating sample IGNIS PDF...")
    path = generate_sample_pdf(job_id="sample-ignis")
    print(f"PDF generated at: {path}")
