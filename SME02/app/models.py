from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from enum import Enum
from datetime import datetime

from app.config import settings


# --- Enums ---

class AgentRole(str, Enum):
    JUNIOR_ANALYST = "Junior Analyst"
    PRICING_STRATEGIST = "Pricing Strategist"
    SENIOR_COPYWRITER = "Senior Copywriter"
    ORCHESTRATOR = "Orchestrator"
    PDF_GENERATOR = "PDF Generator"


class MessageType(str, Enum):
    THINKING = "thinking"
    ACTION = "action"
    RESULT = "result"
    ERROR = "error"
    STATUS = "status"
    COMPLETE = "complete"
    WARNING = "warning"


class JobStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    PRICING = "pricing"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    REVISING = "revising"
    GENERATING_PDF = "generating_pdf"
    COMPLETED = "completed"
    ERROR = "error"


# --- Input Models ---

class RFPInput(BaseModel):
    rfp_text: str = Field(..., description="The raw RFP document text")
    company_name: str = Field(default="Ering Solutions", description="Your SME company name")
    contact_name: str = Field(default="Sales Team", description="Contact person name")
    contact_email: str = Field(default="sales@eringsolutions.com", description="Contact email")
    contact_phone: str = Field(default="+91-9876543210", description="Contact phone")

    @field_validator("rfp_text")
    @classmethod
    def limit_rfp_length(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("RFP text must not be empty.")
        max_len = settings.MAX_RFP_TEXT_CHARS
        if len(v) > max_len:
            raise ValueError(f"RFP text exceeds maximum length ({max_len} characters).")
        return v


# --- Agent Output Models ---

class ScopeItem(BaseModel):
    item_name: str
    description: str
    quantity: int = 1
    specifications: str = ""
    category: str = ""  # hardware, software, service
    is_mandatory: bool = True
    priority: str = "P1"


class ConflictItem(BaseModel):
    """A single detected conflict within the RFP document."""
    field: str                        # e.g. "budget", "warranty_period", "spec"
    section_a: str = ""               # where the first value was found
    value_a: str = ""
    section_b: str = ""               # where the contradictory value was found
    value_b: str = ""
    resolution: str = ""              # which value was prioritized and why
    prioritized_value: str = ""
    confidence: str = "medium"        # low, medium, high


class ConflictReport(BaseModel):
    """Result of intra-document conflict detection (TWIST 2)."""
    conflicts: list[ConflictItem] = []
    has_conflicts: bool = False
    summary: str = ""


class ExtractedRequirements(BaseModel):
    project_name: str = ""
    issuing_company: str = ""
    date_issued: str = ""
    response_deadline: str = ""
    scope_items: list[ScopeItem] = []
    budget_amount: float = 0.0
    budget_currency: str = "INR"
    evaluation_criteria: list[str] = []
    disqualification_criteria: list[str] = []
    compliance_checklist: list[dict] = []
    project_timeline: str = ""
    submission_requirements: list[str] = []
    additional_notes: str = ""
    # TWIST 2 — Conflict Detection
    conflict_report: Optional[ConflictReport] = None


class CompetitorAnalysis(BaseModel):
    competitor_name: str
    product_id: str
    competitor_price: float
    our_price: float
    price_difference: float
    price_difference_pct: float
    can_match: bool
    recommendation: str
    value_adds_suggested: list[str] = []


class LineItem(BaseModel):
    item_name: str
    description: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    total_price: float = 0.0
    matched_product_id: str = ""
    is_value_add: bool = False
    # v2 fields — GST, volume, strategy tracking
    gst_rate: float = 0.18
    tax_amount: float = 0.0
    volume_discount_pct: float = 0.0
    volume_tier_label: str = ""
    strategy_type: str = ""
    is_unverified_estimate: bool = False
    estimate_range: Optional[dict] = None
    # Value-add scoring
    value_add_delivery_cost: float = 0.0
    value_add_perceived_score: int = 0


class PricingStrategy(BaseModel):
    line_items: list[LineItem] = []
    subtotal: float = 0.0
    tax_rate: float = 0.18
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = "INR"
    competitor_analyses: list[CompetitorAnalysis] = []
    value_adds: list[LineItem] = []
    pricing_rationale: str = ""
    strategy_summary: str = ""
    win_probability_score: int = 0
    fx_rate_used: Optional[float] = None


class ProposalSection(BaseModel):
    title: str
    content: str


class ProposalDraft(BaseModel):
    executive_summary: str = ""
    technical_proposal: list[ProposalSection] = []
    project_plan: str = ""
    value_proposition: str = ""
    compliance_matrix: list[dict] = []
    company_profile: str = ""
    support_plan: str = ""
    terms_and_conditions: str = ""


# --- Communication Models ---

class AgentMessage(BaseModel):
    agent: AgentRole
    message_type: MessageType
    content: str
    timestamp: Optional[str] = None


class ReviewRequest(BaseModel):
    """Sent to frontend when all agents complete, for human review."""
    extracted_requirements: Optional[ExtractedRequirements] = None
    pricing_strategy: Optional[PricingStrategy] = None
    proposal_draft: Optional[ProposalDraft] = None


class HumanFeedback(BaseModel):
    """Feedback from the user on the generated output."""
    approved: bool = False
    changes: list["ChangeRequest"] = []


class ChangeRequest(BaseModel):
    """A specific change request from the user."""
    target_agent: AgentRole
    instruction: str
    section: str = ""  # optional: which section to modify


class SupportTicket(BaseModel):
    """Auto-filled CRM support ticket generated from pipeline output (TWIST 1)."""
    ticket_id: str = ""
    client_company: str = ""          # from RFPInput
    issue_summary: str = ""
    issue_category: str = ""          # procurement, technical, contract, general
    relevant_context: str = ""        # key facts from extraction + pricing
    suggested_resolution: str = ""    # actionable next steps
    conflict_report: Optional[ConflictReport] = None
    confidence: str = "medium"
    auto_generated: bool = True
    created_at: str = ""


class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    rfp_input: Optional[RFPInput] = None
    extracted_requirements: Optional[ExtractedRequirements] = None
    pricing_strategy: Optional[PricingStrategy] = None
    proposal_draft: Optional[ProposalDraft] = None
    support_ticket: Optional[SupportTicket] = None
    pdf_path: Optional[str] = None
    messages: list[AgentMessage] = []
    revision_count: int = 0


from typing import TypedDict

class GraphState(TypedDict, total=False):
    job_id: str
    status: JobStatus
    rfp_input: RFPInput
    extracted_requirements: ExtractedRequirements
    pricing_strategy: PricingStrategy
    proposal_draft: ProposalDraft
    support_ticket: SupportTicket
    feedback: HumanFeedback
    pdf_path: str
    messages: list[AgentMessage]
    revision_count: int


HumanFeedback.model_rebuild()
