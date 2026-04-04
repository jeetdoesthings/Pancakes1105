"""
PDF Generator Service (xhtml2pdf + Jinja2)
==========================================
Creates professional quotation PDFs from structured proposal data.
"""

import os
from datetime import datetime
from jinja2 import Template, Environment, FileSystemLoader
from xhtml2pdf import pisa
from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft
from app.config import settings


def format_currency_amount(amount, currency: str = "INR") -> str:
    """Format a numeric amount for display in PDFs and tables."""
    try:
        val = float(amount)
    except (ValueError, TypeError):
        return "—"
    if currency == "INR":
        return f"₹{val:,.0f}"
    if currency == "USD":
        return f"${val:,.2f}"
    return f"{currency} {val:,.2f}"


# ── HTML Template (SME02) ─────────────────────────────────────────────────────
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

  .doc-title {
    text-align: center;
    font-size: 22pt;
    font-weight: bold;
    color: #1e3a8a;
    margin-bottom: 20px;
  }

  .section-header {
    font-size: 11pt;
    font-weight: bold;
    color: #1e3a8a;
    margin: 15px 0 5px 0;
    padding-bottom: 2px;
    border-bottom: 1px solid #e2e8f0;
  }

  .body-text {
    font-size: 9pt;
    color: #334155;
    margin: 6px 0 12px 0;
    white-space: pre-wrap;
  }

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

  <div class="doc-title">Formal Proposal &amp; Quotation</div>

  <div class="section-header">Client Information</div>
  <table>
    <tr><td class="label-col">Client Name</td><td>{{ client_name }}</td></tr>
    <tr><td class="label-col">RFP Reference</td><td>{{ rfp_ref }}</td></tr>
    <tr><td class="label-col">Project Scope</td><td>{{ scope_summary }}</td></tr>
    <tr><td class="label-col">Deadline</td><td>{{ deadline }}</td></tr>
    <tr><td class="label-col">Stated Budget</td><td>{{ budget }}</td></tr>
  </table>

  {% if executive_summary %}
  <div class="section-header">Executive Summary</div>
  <div class="body-text">{{ executive_summary }}</div>
  {% endif %}

  {% if requirements %}
  <div class="section-header">Key Requirements</div>
  <ul>
    {% for req in requirements[:8] %}
    <li>{{ req.item_name }}: {{ req.description }}</li>
    {% endfor %}
  </ul>
  {% endif %}

  <div class="section-header">Strategic Approach</div>
  <div class="strategy-box {{ 'strategy-box-pivot' if is_pivot else 'strategy-box-match' }}">
    <div class="strategy-label {{ 'strategy-label-pivot' if is_pivot else 'strategy-label-match' }}">
      {{ "STRATEGY: VALUE-ADD PIVOT" if is_pivot else "STRATEGY: COMPETITIVE MATCH" }}
    </div>
    <div class="rationale">"{{ rationale }}"</div>
  </div>

  <div class="section-header">Investment Summary</div>
  <table>
    <tr><th>Description</th><th style="text-align:right">Amount ({{ currency }})</th></tr>
    {% for item in line_items %}
    <tr>
      <td><b>{{ item.item_name }}</b><br><small>{{ item.description }}</small></td>
      <td style="text-align:right">{{ format_currency_amount(item.total_price, currency) if not item.is_value_add else 'INCLUDED' }}</td>
    </tr>
    {% endfor %}
    <tr style="background-color:#eff6ff; font-weight:bold">
      <td>Total Investment</td>
      <td style="text-align:right">{{ final_price_fmt }}</td>
    </tr>
  </table>

  {% if competitor_name %}
  <div class="section-header">Market Analysis</div>
  <table>
    <tr><td class="label-col">Primary Competitor</td><td>{{ competitor_name }}</td></tr>
    <tr><td class="label-col">Competitor Price</td><td>{{ competitor_price_fmt }}</td></tr>
    <tr><td class="label-col">Our Price</td><td>{{ final_price_fmt }}</td></tr>
    <tr><td class="label-col">Projected Delta</td><td>{{ delta }}</td></tr>
  </table>
  {% endif %}

  <div class="footer">
    This quotation is valid for 30 days from the date of issue.<br>
    Generated by SME02 — Autonomous RFP Response Orchestrator
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
        self.template_env.filters["format_currency"] = self._format_currency
        self.template_env.filters["format_number"] = self._format_number

        import markdown
        self.template_env.filters["markdown"] = lambda text: markdown.markdown(text) if text else ""

    @staticmethod
    def _format_currency(value, currency="INR"):
        return format_currency_amount(value, currency)

    @staticmethod
    def _format_number(value):
        try:
            return f"{float(value):,.0f}"
        except (ValueError, TypeError):
            return "0"

    @staticmethod
    def _safe_iterable(value):
      """Return a list for any iterable-like value, else an empty list."""
      if value is None or value is NotImplemented:
        return []
      if isinstance(value, list):
        return value
      if isinstance(value, tuple):
        return list(value)
      return []

    @staticmethod
    def _safe_text(value) -> str:
      """Return a string for text fields and guard against sentinels."""
      if value is None or value is NotImplemented:
        return ""
      return str(value)

    @staticmethod
    def _default_payment_milestones() -> list[dict]:
      return [
        {"milestone": "Purchase Order / Contract Signing", "percent": 40, "trigger": "On PO release and project kickoff"},
        {"milestone": "Delivery / Implementation", "percent": 40, "trigger": "On delivery or completion of implementation phase"},
        {"milestone": "UAT Sign-off / Final Handover", "percent": 20, "trigger": "On final acceptance and handover"},
      ]

    @staticmethod
    def _default_assumptions() -> list[str]:
      return [
        "Client will provide timely access to site, stakeholders, and required infrastructure.",
        "Any scope changes after sign-off will be handled through a formal change request.",
        "All third-party licenses, if required, are either client-provided or quoted separately.",
        "Project timelines are based on mutually agreed dependencies and response SLAs.",
      ]

    @staticmethod
    def _default_exclusions() -> list[str]:
      return [
        "Civil, electrical, and structural modifications unless explicitly mentioned in scope.",
        "Out-of-scope integrations and custom developments not listed in the approved BOQ.",
        "Regulatory approvals, statutory fees, and duties outside quoted taxes.",
        "Travel, lodging, and on-site expenses for locations not listed in the RFP unless stated.",
      ]

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
        """Generate a professional proposal PDF using xhtml2pdf."""
        output_filename = f"quotation_{job_id}.pdf"
        output_path = os.path.join(settings.OUTPUT_DIR, output_filename)

        # Defensive normalization for occasionally malformed agent payloads.
        # Prevents runtime errors like: 'NotImplementedType' object is not iterable.
        pricing.line_items = self._safe_iterable(getattr(pricing, "line_items", []))
        pricing.value_adds = self._safe_iterable(getattr(pricing, "value_adds", []))
        pricing.competitor_analyses = self._safe_iterable(getattr(pricing, "competitor_analyses", []))

        proposal.technical_proposal = self._safe_iterable(getattr(proposal, "technical_proposal", []))
        proposal.compliance_matrix = self._safe_iterable(getattr(proposal, "compliance_matrix", []))
        proposal.executive_summary = self._safe_text(getattr(proposal, "executive_summary", ""))
        proposal.project_plan = self._safe_text(getattr(proposal, "project_plan", ""))
        proposal.value_proposition = self._safe_text(getattr(proposal, "value_proposition", ""))
        proposal.company_profile = self._safe_text(getattr(proposal, "company_profile", ""))
        proposal.support_plan = self._safe_text(getattr(proposal, "support_plan", ""))
        proposal.terms_and_conditions = self._safe_text(getattr(proposal, "terms_and_conditions", ""))

        # Build line-level commercial math sheet (client-auditable pricing logic)
        calc_rows: list[dict] = []
        for idx, item in enumerate(pricing.line_items, start=1):
            qty = int(getattr(item, "quantity", 1) or 1)
            unit = float(getattr(item, "unit_price", 0.0) or 0.0)
            base_amount = unit * qty
            gst_rate = float(getattr(item, "gst_rate", pricing.tax_rate) or 0.0)
            gst_amount = float(getattr(item, "tax_amount", base_amount * gst_rate) or 0.0)
            line_total = base_amount + gst_amount

            calc_rows.append({
                "sr_no": idx,
                "item_name": getattr(item, "item_name", ""),
                "description": getattr(item, "description", ""),
                "quantity": qty,
                "unit_price": unit,
                "base_amount": base_amount,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "line_total": line_total,
                "strategy_type": getattr(item, "strategy_type", "BASELINE"),
                "volume_discount_pct": float(getattr(item, "volume_discount_pct", 0.0) or 0.0),
                "volume_tier_label": getattr(item, "volume_tier_label", ""),
                "is_unverified_estimate": bool(getattr(item, "is_unverified_estimate", False)),
            })

        # Optional value-add sheet
        value_add_rows = []
        for idx, va in enumerate(pricing.value_adds, start=1):
            value_add_rows.append({
                "sr_no": idx,
                "item_name": getattr(va, "item_name", ""),
                "description": getattr(va, "description", ""),
                "delivery_cost": float(getattr(va, "value_add_delivery_cost", 0.0) or 0.0),
                "perceived_score": int(getattr(va, "value_add_perceived_score", 0) or 0),
            })

        payment_milestones = self._default_payment_milestones()
        assumptions = self._default_assumptions()
        exclusions = self._default_exclusions()

        template = self.template_env.get_template("quotation.html")
        context = {
            "proposal_id": job_id.upper(),
            "date": datetime.now().strftime("%d %b %Y"),
            "company_name": company_name,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "requirements": requirements,
            "pricing": pricing,
            "proposal": proposal,
            "currency": pricing.currency,
            "has_value_adds": bool(pricing.value_adds),
            "calculation_rows": calc_rows,
            "value_add_rows": value_add_rows,
            "payment_milestones": payment_milestones,
            "assumptions": assumptions,
            "exclusions": exclusions,
            "quotation_validity_days": 30,
            "include_internal_appendix": False,
        }

        html_str = template.render(**context)

        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html_str, dest=f)

        if pisa_status.err:
            raise RuntimeError(f"PDF generation failed: {pisa_status.err}")

        return output_path
