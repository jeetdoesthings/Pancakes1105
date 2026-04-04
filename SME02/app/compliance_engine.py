"""
Compliance Validation Engine
==============================
Extracts mandatory clauses from RFP requirements and validates
the proposal against them. Flags risks before final output.

Design Principle: Graceful Degradation (Section 7.4)
"""

from typing import List, Dict, Any
from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft


# Keywords that typically signal mandatory requirements in RFPs
COMPLIANCE_KEYWORDS = [
    "must", "shall", "required", "mandatory", "compliance",
    "certif", "iso", "gdpr", "sla", "warranty", "insurance",
    "bonded", "licensed", "registered", "deadline",
]


def extract_compliance_clauses(requirements: ExtractedRequirements) -> List[str]:
    """
    Scan extracted requirements for mandatory compliance clauses.
    Returns a list of flagged clauses that must be addressed in the proposal.
    """
    clauses = []
    
    # Check submission requirements
    for req in requirements.submission_requirements:
        req_lower = req.lower()
        if any(kw in req_lower for kw in COMPLIANCE_KEYWORDS):
            clauses.append(f"[SUBMISSION] {req}")
    
    # Check evaluation criteria
    for crit in requirements.evaluation_criteria:
        crit_lower = crit.lower()
        if any(kw in crit_lower for kw in COMPLIANCE_KEYWORDS):
            clauses.append(f"[EVALUATION] {crit}")
    
    # Check scope item specifications
    for item in requirements.scope_items:
        spec_lower = item.specifications.lower() if item.specifications else ""
        desc_lower = item.description.lower() if item.description else ""
        combined = spec_lower + " " + desc_lower
        if any(kw in combined for kw in COMPLIANCE_KEYWORDS):
            clauses.append(f"[SPEC:{item.item_name}] {item.specifications or item.description}")
    
    # Check additional notes
    if requirements.additional_notes:
        notes_lower = requirements.additional_notes.lower()
        if any(kw in notes_lower for kw in COMPLIANCE_KEYWORDS):
            clauses.append(f"[NOTES] {requirements.additional_notes[:200]}")
    
    return clauses


def validate_proposal_compliance(
    requirements: ExtractedRequirements,
    pricing: PricingStrategy,
    proposal: ProposalDraft,
) -> Dict[str, Any]:
    """
    Cross-check the proposal against compliance requirements.
    Returns a validation report with pass/fail status and risk flags.
    """
    report = {
        "passed": True,
        "risks": [],
        "warnings": [],
        "checks_performed": 0,
    }
    
    clauses = extract_compliance_clauses(requirements)
    report["compliance_clauses_found"] = len(clauses)
    report["clauses"] = clauses
    
    # Check 1: Budget compliance
    if requirements.budget_amount > 0 and pricing.total > requirements.budget_amount:
        report["risks"].append(
            f"BUDGET EXCEEDED: Proposal total ({pricing.currency} {pricing.total:,.0f}) "
            f"exceeds stated budget ({pricing.currency} {requirements.budget_amount:,.0f})"
        )
        report["passed"] = False
    report["checks_performed"] += 1
    
    # Check 2: All scope items addressed
    scope_names = {item.item_name.lower() for item in requirements.scope_items}
    priced_names = {item.item_name.lower() for item in pricing.line_items}
    missing = scope_names - priced_names
    if missing:
        report["warnings"].append(
            f"UNADDRESSED ITEMS: {len(missing)} scope items not found in pricing: "
            f"{', '.join(missing)}"
        )
    report["checks_performed"] += 1
    
    # Check 3: Deadline mentioned in proposal
    if requirements.response_deadline:
        proposal_text = (
            proposal.executive_summary + " " +
            proposal.project_plan + " " +
            " ".join(s.content for s in proposal.technical_proposal)
        ).lower()
        if requirements.response_deadline.lower() not in proposal_text:
            report["warnings"].append(
                f"DEADLINE NOT REFERENCED: Response deadline '{requirements.response_deadline}' "
                f"not found in proposal body."
            )
    report["checks_performed"] += 1
    
    # Check 4: Terms and conditions present
    if not proposal.terms_and_conditions or len(proposal.terms_and_conditions.strip()) < 50:
        report["warnings"].append("MISSING T&C: Terms and conditions section is empty or too short.")
    report["checks_performed"] += 1
    
    # Check 5: Company profile present
    if not proposal.company_profile or len(proposal.company_profile.strip()) < 50:
        report["warnings"].append("MISSING PROFILE: Company profile section is empty or too short.")
    report["checks_performed"] += 1
    
    if report["risks"]:
        report["passed"] = False
    
    return report
