"""
PDF Generator Service (IGNIS xhtml2pdf Edition)
=============================================
Creates professional quotation PDFs using xhtml2pdf + Jinja2 HTML templates.
Restored as per user request to use the "Ignis Solutions" design.
"""

import os
from typing import Dict, Any
from jinja2 import Template, Environment, FileSystemLoader
from xhtml2pdf import pisa
from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft
from app.config import settings


def _format_currency(amount, currency="USD") -> str:
    """Format a number as currency."""
    try:
        val = float(amount)
        if currency == "INR":
            return f"Rs. {val:,.0f}"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


# ── HTML Template ────────────────────────────────────────────────────────────────
# IGNIS Solutions Inc. Premium Template
PDF_TEMPLATE = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {
    size: a4 portrait;
    margin: 1.5cm;
  }

  body {
    font-family: Helvetica, Arial, sans-serif;
    color: #1e293b;
    line-height: 1.4;
    font-size: 10pt;
  }

  /* ── Header ── */
  .header-table {
    width: 100%;
    margin-bottom: 5px;
  }
  .company-name {
    font-size: 20pt;
    font-weight: bold;
    color: #1e3a8a;
  }
  .company-tagline {
    font-size: 8pt;
    color: #64748b;
  }
  .header-right {
    text-align: right;
    font-size: 8pt;
    color: #64748b;
  }
  .divider {
    height: 2px;
    background-color: #1e3a8a;
    margin: 10px 0 20px 0;
  }

  /* ── Title ── */
  .doc-title {
    text-align: center;
    font-size: 22pt;
    font-weight: bold;
    color: #1e3a8a;
    margin-bottom: 20px;
  }

  /* ── Section headers ── */
  .section-header {
    font-size: 11pt;
    font-weight: bold;
    color: #1e3a8a;
    margin: 15px 0 5px 0;
    padding-bottom: 2px;
    border-bottom: 1px solid #e2e8f0;
  }

  /* ── Tables ── */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 5px 0 10px 0;
  }
  th {
    background-color: #1e3a8a;
    color: white;
    font-weight: bold;
    font-size: 9pt;
    padding: 6px;
    text-align: left;
  }
  td {
    padding: 6px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 9pt;
  }
  .label-col { font-weight: bold; color: #1e3a8a; width: 30%; }

  /* ── Strategy badges ── */
  .strategy-box {
    padding: 10px;
    margin: 10px 0;
    border: 1px solid #e2e8f0;
  }
  .strategy-box-pivot {
    background-color: #fff7ed;
    border-color: #f97316;
  }
  .strategy-box-match {
    background-color: #f0fdf4;
    border-color: #22c55e;
  }
  .strategy-label {
    font-size: 9pt;
    font-weight: bold;
    margin-bottom: 4px;
  }
  .strategy-label-pivot { color: #ea580c; }
  .strategy-label-match { color: #16a34a; }
  .rationale {
    font-style: italic;
    color: #475569;
    font-size: 9pt;
  }

  /* ── Footer ── */
  .footer {
    margin-top: 30px;
    text-align: center;
    font-size: 7pt;
    color: #94a3b8;
    border-top: 1px solid #e2e8f0;
    padding-top: 8px;
  }
</style>
</head>
<body>
  <!-- Header -->
  <table class="header-table">
    <tr>
      <td>
        <div class="company-name">{{ company_name }}</div>
        <div class="company-tagline">Intelligent Business Solutions</div>
      </td>
      <td class="header-right">
        Proposal Reference<br>
        AUTO-{{ doc_id[:12] if doc_id else 'GEN' }}
      </td>
    </tr>
  </table>
  <div class="divider"></div>

  <!-- Title -->
  <div class="doc-title">Formal Proposal &amp; Quotation</div>

  <!-- Client Details -->
  <div class="section-header">Client Information</div>
  <table>
    <tr><td class="label-col">Client Name</td><td>{{ client_name }}</td></tr>
    <tr><td class="label-col">RFP Reference</td><td>{{ rfp_ref }}</td></tr>
    <tr><td class="label-col">Project Scope</td><td>{{ scope_summary }}</td></tr>
    <tr><td class="label-col">Deadline</td><td>{{ deadline }}</td></tr>
    <tr><td class="label-col">Stated Budget</td><td>{{ budget }}</td></tr>
  </table>

  <!-- Requirements -->
  {% if requirements %}
  <div class="section-header">Key Requirements</div>
  <ul>
    {% for req in requirements[:8] %}
    <li>{{ req.item_name }}: {{ req.description }}</li>
    {% endfor %}
  </ul>
  {% endif %}

  <!-- Strategy Section -->
  <div class="section-header">Strategic Approach</div>
  <div class="strategy-box {{ 'strategy-box-pivot' if is_pivot else 'strategy-box-match' }}">
    <div class="strategy-label {{ 'strategy-label-pivot' if is_pivot else 'strategy-label-match' }}">
      {{ "STRATEGY: VALUE-ADD PIVOT" if is_pivot else "STRATEGY: COMPETITIVE MATCH" }}
    </div>
    <div class="rationale">"{{ rationale }}"</div>
  </div>

  <!-- Pricing Table -->
  <div class="section-header">Investment Summary</div>
  <table>
    <tr><th>Description</th><th style="text-align:right">Amount ({{ currency }})</th></tr>
    {% for item in line_items %}
    <tr>
      <td><b>{{ item.item_name }}</b><br><small>{{ item.description }}</small></td>
      <td style="text-align:right">{{ _format_currency(item.total_price, currency) if not item.is_value_add else 'INCLUDED' }}</td>
    </tr>
    {% endfor %}
    <tr style="background-color:#eff6ff; font-weight:bold">
      <td>Total Investment</td>
      <td style="text-align:right">{{ final_price_fmt }}</td>
    </tr>
  </table>

  <!-- Market Analysis -->
  {% if competitor_name %}
  <div class="section-header">Market Analysis</div>
  <table>
    <tr><td class="label-col">Primary Competitor</td><td>{{ competitor_name }}</td></tr>
    <tr><td class="label-col">Competitor Price</td><td>{{ competitor_price_fmt }}</td></tr>
    <tr><td class="label-col">Our Price</td><td>{{ final_price_fmt }}</td></tr>
    <tr><td class="label-col">Projected Delta</td><td>{{ delta }}</td></tr>
  </table>
  {% endif %}

  <!-- Footer -->
  <div class="footer">
    This quotation is valid for 30 days from the date of issue.<br>
    Generated autonomously by IGNIS RFP Orchestrator AI System
  </div>
</body>
</html>
""")


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
        company_name: str = "IGNIS Solutions Inc.",
        contact_name: str = "Sales Team",
        contact_email: str = "sales@ignissolutions.com",
        contact_phone: str = "+91-9876543210",
    ) -> str:
        """Generate a professional proposal PDF using xhtml2pdf."""
        output_filename = f"quotation_{job_id}.pdf"
        output_path = os.path.join(settings.OUTPUT_DIR, output_filename)

        # Map data models to template context
        is_pivot = any(not c.can_match for c in pricing.competitor_analyses)
        
        comp_name = pricing.competitor_analyses[0].competitor_name if pricing.competitor_analyses else None
        comp_price = pricing.competitor_analyses[0].competitor_price if pricing.competitor_analyses else 0
        delta = f"{abs(pricing.competitor_analyses[0].price_difference_pct):.1f}%" if pricing.competitor_analyses else "N/A"

        context = {
            "company_name": company_name,
            "doc_id": job_id.upper(),
            "client_name": requirements.issuing_company or "Valued Client",
            "rfp_ref": requirements.project_name or "N/A",
            "scope_summary": f"Proposal for {requirements.project_name}",
            "deadline": requirements.response_deadline or "N/A",
            "budget": _format_currency(requirements.budget_amount, pricing.currency),
            "requirements": requirements.scope_items,
            "is_pivot": is_pivot,
            "rationale": pricing.strategy_summary or "Standard pricing applied.",
            "line_items": pricing.line_items,
            "currency": pricing.currency,
            "final_price_fmt": _format_currency(pricing.total, pricing.currency),
            "competitor_name": comp_name,
            "competitor_price_fmt": _format_currency(comp_price, pricing.currency),
            "delta": delta,
            "_format_currency": _format_currency
        }

        html_str = PDF_TEMPLATE.render(**context)
        
        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html_str, dest=f)
            
        if pisa_status.err:
            raise RuntimeError(f"PDF generation failed: {pisa_status.err}")

        return output_path
