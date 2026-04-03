import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.services.pdf_generator import PDFGenerator
from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft, LineItem, CompetitorAnalysis, ScopeItem, ProposalSection

def test_ignis_pdf():
    gen = PDFGenerator()
    
    # Mock Data
    reqs = ExtractedRequirements(
        project_name="IT Infrastructure Upgrade",
        issuing_company="TechCorp India",
        budget_amount=5000000,
        scope_items=[ScopeItem(item_name="Server Rack", quantity=2, category="hardware")]
    )
    
    # Trigger a PIVOT strategy (can_match=False)
    pricing = PricingStrategy(
        line_items=[LineItem(item_name="Server Rack", quantity=2, unit_price=2500000, total_price=5000000)],
        subtotal=5000000,
        total=5900000,
        currency="INR",
        strategy_summary="Pivoting to value-differentiation as competitor price is below cost.",
        competitor_analyses=[CompetitorAnalysis(
            competitor_name="CheapIT",
            product_id="SR-100",
            competitor_price=1500000,
            our_price=2500000,
            price_difference=1000000,
            price_difference_pct=40.0,
            can_match=False,
            recommendation="Pivot"
        )]
    )
    
    proposal = ProposalDraft(
        executive_summary="This is a professional proposal for TechCorp.",
        technical_proposal=[ProposalSection(title="Hardware", content="Standard rack setup.")]
    )
    
    print("DEBUG: Generating Ignis-Style PDF...")
    output_path = gen.generate(
        job_id="test-ignis",
        requirements=reqs,
        pricing=pricing,
        proposal=proposal
    )
    print(f"DEBUG: PDF Generated at {output_path}")

if __name__ == "__main__":
    test_ignis_pdf()
