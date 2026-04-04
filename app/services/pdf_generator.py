"""
PDF Generator Service — SME02 Professional Quotation
=====================================================
Creates professional quotation PDFs using xhtml2pdf + Jinja2 HTML templates.
Uses the external quotation.html template from app/templates/ with full:
  - Cover page
  - Markdown-rendered proposal sections
  - Pricing table with value-add badges
  - Algorithm Decision Log (Criticism 1A)
  - Standardised RFP Schema (Criticism 2C)
  - Historical RFP Intelligence (Criticism 3D)
  - AI Optimization Report
"""

import os
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import markdown
from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft
from app.config import settings


class PDFGenerator:
    """Generates professional PDF quotations using the external quotation.html template."""

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(settings.TEMPLATES_DIR),
            autoescape=False,
        )
        self.env.filters["format_currency"] = self._format_currency
        self.env.filters["format_number"] = self._format_number
        self.env.filters["markdown"] = lambda text: markdown.markdown(text or "", extensions=["tables"])

    @staticmethod
    def _format_currency(value, currency="INR"):
        """Format a number as currency."""
        if value is None:
            return "N/A"
        try:
            val = float(value)
        except (ValueError, TypeError):
            return "N/A"
        if currency == "INR":
            return f"\u20b9{val:,.0f}"
        elif currency == "USD":
            return f"${val:,.2f}"
        elif currency == "EUR":
            return f"\u20ac{val:,.2f}"
        elif currency == "GBP":
            return f"\u00a3{val:,.2f}"
        return f"{currency} {val:,.2f}"

    @staticmethod
    def _format_number(value):
        """Format a number with commas."""
        try:
            return f"{float(value):,.0f}"
        except (ValueError, TypeError):
            return "0"

    def generate(
        self,
        job_id: str,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        proposal: ProposalDraft,
        company_name: str = "SME02",
        contact_name: str = "Sales Team",
        contact_email: str = "sales@company.com",
        contact_phone: str = "+91-9876543210",
        universal_rfp: dict = None,
        similar_rfps: list = None,
    ) -> str:
        """Generate a professional proposal PDF using xhtml2pdf + external template."""
        output_filename = f"quotation_{job_id}.pdf"
        output_path = os.path.join(settings.OUTPUT_DIR, output_filename)

        # Load the external quotation.html template
        template = self.env.get_template("quotation.html")

        # Determine currency display
        currency = pricing.currency or "INR"

        # Build context for the template
        context = {
            # Core identity
            "company_name": company_name,
            "proposal_id": f"SME02-{job_id.upper()[:8]}",
            "date": None,  # Will use today
            "contact_name": contact_name,
            "contact_email": contact_email,
            "contact_phone": contact_phone,

            # Requirements
            "requirements": requirements,

            # Pricing
            "pricing": pricing,
            "currency": currency,
            "has_value_adds": bool(pricing.value_adds),

            # Proposal
            "proposal": proposal,

            # Algorithm Decision Log (Criticism 1A)
            "algorithm_decisions": [
                {
                    "item_name": ca.competitor_name or "N/A",
                    "product_id": ca.product_id,
                    "strategy": ca.algorithm_strategy or "BASELINE",
                    "input_cost": ca.algorithm_input_cost,
                    "input_competitor_prices": ca.algorithm_input_competitor_prices,
                    "input_margin_target": ca.algorithm_input_margin_target,
                    "threshold": ca.algorithm_threshold,
                    "output_price": ca.algorithm_output_price,
                    "output_rationale": ca.algorithm_output_rationale,
                }
                for ca in pricing.competitor_analyses
                if ca.algorithm_strategy  # Only include if algorithm data exists
            ],

            # Standardised RFP Schema (Criticism 2C)
            "universal_rfp": universal_rfp,

            # Historical RFP Intelligence (Criticism 3D)
            "similar_rfps": similar_rfps or [],

            # Currency conversion (Twist 1)
            "currency_conversions": self._get_currency_conversions(pricing.total, currency),
        }

        from datetime import date
        context["date"] = date.today().strftime("%B %d, %Y")

        try:
            html_str = template.render(**context)
        except Exception as e:
            import traceback
            raise RuntimeError(f"Template rendering failed: {e}\n{traceback.format_exc()}")

        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html_str, dest=f)

        if pisa_status.err:
            raise RuntimeError(f"PDF generation failed: {pisa_status.err}")

        return output_path

    def _get_currency_conversions(self, total: float, base_currency: str) -> list[dict]:
        """Return currency conversion equivalents from tax_rates.json.
        
        currency_rates are INR-based: e.g. USD=85.50 means 1 USD = ₹85.50 INR.
        To convert FROM base_currency TO other:
          amount_in_INR = total * rate_of_base
          amount_in_target = amount_in_INR / rate_of_target
        """
        try:
            import json
            filepath = os.path.join(settings.DATA_DIR, "tax_rates.json")
            with open(filepath, "r") as f:
                data = json.load(f)
            rates = data.get("currency_rates", {})
        except Exception:
            rates = {"INR": 1.0, "USD": 85.50, "EUR": 92.30, "GBP": 107.80}

        base_rate = rates.get(base_currency, 1.0)
        if base_rate <= 0:
            base_rate = 1.0

        conversions = []
        for curr, rate in rates.items():
            if curr != base_currency and rate > 0:
                # Convert: total in base_currency → INR → target currency
                amount_in_inr = total * base_rate
                converted = round(amount_in_inr / rate, 2)
                # Exchange rate display: "1 USD = ₹85.50"
                if base_currency == "INR":
                    rate_display = f"1 {base_currency} = {round(1/rate, 4)} {curr}"
                else:
                    rate_display = f"1 {base_currency} = {round(base_rate/rate, 4)} {curr}"

                conversions.append({
                    "currency": curr,
                    "symbol": {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "INR": "\u20b9"}.get(curr, curr),
                    "amount": converted,
                    "rate_display": rate_display,
                })
        return conversions
