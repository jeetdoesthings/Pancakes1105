from langchain_core.tools import tool

@tool
def template_filler_tool(template_name: str, structured_data: str) -> str:
    """Fills a standard proposal template section with the provided structured data.
    Use this tool to reliably inject deterministic facts (like pricing and company history) into standard templates.
    """
    templates = {
        "company_profile": "We are {company_name}, bringing 10+ years of IT infrastructure expertise. We hold vital industry certifications and prioritize resilient enterprise solutions.",
        "terms_and_conditions": "1. All prices exclusive of taxes.\n2. 50% advance, 50% upon delivery.\n3. Standard manufacturer warranties apply augmented by our premium SLA.",
        "support_plan": "Support Plan: 24/7 priority response with 4-hour SLA on critical issues. Quarterly preventive maintenance checks included."
    }
    
    if template_name in templates:
        return templates[template_name]
    return f"Template '{template_name}' not found. Please dynamically write the section."
