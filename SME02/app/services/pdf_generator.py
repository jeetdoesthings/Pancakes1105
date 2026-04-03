"""
PDF Generator Service
=====================
Generates professional, boardroom-ready PDF quotations
using WeasyPrint and Jinja2 HTML templates.
"""

import os
import sys
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft
from app.config import settings

# Ensure Homebrew libraries are discoverable for WeasyPrint's cffi bindings
_HOMEBREW_LIB = "/opt/homebrew/lib"
if os.path.isdir(_HOMEBREW_LIB):
    _current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if _HOMEBREW_LIB not in _current:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            f"{_HOMEBREW_LIB}:{_current}" if _current else _HOMEBREW_LIB
        )


class PDFGenerator:
    """Generates professional PDF quotations from proposal data."""

    def __init__(self):
        self.template_env = Environment(
            loader=FileSystemLoader(settings.TEMPLATES_DIR)
        )
        # Add custom filters
        self.template_env.filters["format_currency"] = self._format_currency
        self.template_env.filters["format_number"] = self._format_number
        
        import markdown
        self.template_env.filters["markdown"] = lambda text: markdown.markdown(text) if text else ""

    @staticmethod
    def _format_currency(value, currency="INR"):
        """Format a number as currency."""
        if currency == "INR":
            return f"₹{value:,.0f}"
        elif currency == "USD":
            return f"${value:,.2f}"
        return f"{currency} {value:,.2f}"

    @staticmethod
    def _format_number(value):
        """Format a number with commas."""
        return f"{value:,.0f}"

    def generate(
        self,
        job_id: str,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        proposal: ProposalDraft,
        company_name: str = "Ering Solutions",
        contact_name: str = "Sales Team",
        contact_email: str = "sales@eringsolutions.com",
        contact_phone: str = "+91-9876543210",
    ) -> str:
        """Generate a PDF quotation and return the file path."""

        template = self.template_env.get_template("quotation.html")

        # Prepare template data
        context = {
            "company_name": company_name,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "date": datetime.now().strftime("%B %d, %Y"),
            "proposal_id": f"SME02-{job_id.upper()}",
            "requirements": requirements,
            "pricing": pricing,
            "proposal": proposal,
            "currency": pricing.currency,
            "has_value_adds": len(pricing.value_adds) > 0,
        }

        # Render HTML
        html_content = template.render(**context)

        # Generate PDF
        output_filename = f"quotation_{job_id}.pdf"
        output_path = os.path.join(settings.OUTPUT_DIR, output_filename)

        from weasyprint import HTML
        HTML(string=html_content).write_pdf(output_path)

        return output_path
