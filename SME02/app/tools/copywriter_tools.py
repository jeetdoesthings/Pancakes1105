from langchain_core.tools import tool

@tool
def template_filler_tool(template_name: str, structured_data: str) -> str:
    """Fills a standard proposal template section with the provided structured data.
    Use this tool to reliably inject deterministic facts (like pricing and company history) into standard templates.
    """
    templates = {
        "company_profile": (
            "{company_name} is an enterprise solution partner delivering procurement-led technology and services programs. "
            "Our execution model combines technical governance, commercial discipline, and measurable SLA-backed outcomes.\n\n"
            "Core strengths:\n"
            "- Structured pre-sales discovery and compliance-led proposal engineering\n"
            "- Controlled delivery governance with milestone tracking and risk registers\n"
            "- Post-deployment support with incident, problem, and change management workflows"
        ),
        "terms_and_conditions": (
            "1. Commercial Basis: Prices are quoted in the agreed billing currency and are exclusive of applicable statutory taxes unless explicitly stated.\n"
            "2. Taxes & Duties: GST / applicable taxes shall be charged at actuals as per prevailing law on invoice date.\n"
            "3. Payment Terms: Milestone-based billing as per commercial schedule in this proposal; delayed payments may attract applicable finance charges.\n"
            "4. Delivery & Acceptance: Delivery timelines are subject to client dependencies and formal acceptance is based on agreed completion criteria.\n"
            "5. Warranty & Support: Warranty and support obligations apply as specified in the support section and OEM policy documents.\n"
            "6. Change Control: Scope deviations are governed through documented change requests with commercial impact assessment.\n"
            "7. Confidentiality: Both parties shall protect confidential and proprietary information under NDA-equivalent obligations.\n"
            "8. Liability: Total liability is limited to contract value except in cases of fraud, willful misconduct, or statutory non-excludable obligations.\n"
            "9. Validity: This quotation remains valid for 30 days from issuance unless withdrawn or superseded in writing.\n"
            "10. Governing Law & Jurisdiction: Subject to mutually agreed contractual jurisdiction at final award stage."
        ),
        "support_plan": (
            "Support & Maintenance Framework:\n"
            "- Service Window: 24x7 remote support with defined escalation matrix\n"
            "- SLA Commitments: P1 response <= 4 hours, P2 <= 8 business hours, P3 <= next business day\n"
            "- Preventive Activities: Quarterly health checks and optimization recommendations\n"
            "- Governance: Monthly service review report covering incidents, root-cause trends, and improvement actions"
        )
    }
    
    if template_name in templates:
        return templates[template_name]
    return f"Template '{template_name}' not found. Please dynamically write the section."
