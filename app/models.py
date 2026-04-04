from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


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


# --- Agent Output Models ---

class ScopeItem(BaseModel):
    item_name: str
    description: str
    quantity: int = 1
    specifications: str = ""
    category: str = ""  # hardware, software, service


class ExtractedRequirements(BaseModel):
    project_name: str = ""
    issuing_company: str = ""
    date_issued: str = ""
    response_deadline: str = ""
    scope_items: list[ScopeItem] = []
    budget_amount: float = 0.0
    budget_currency: str = "INR"
    evaluation_criteria: list[str] = []
    project_timeline: str = ""
    submission_requirements: list[str] = []
    additional_notes: str = ""


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
    # Algorithm Decision Log fields (Criticism 1A)
    algorithm_strategy: str = ""  # MATCH / PIVOT / BASELINE
    algorithm_input_cost: float = 0.0
    algorithm_input_competitor_prices: list[float] = []
    algorithm_input_margin_target: float = 0.0
    algorithm_threshold: str = ""  # e.g. "min_comp=140 > cost=100 → MATCH"
    algorithm_output_price: float = 0.0
    algorithm_output_rationale: str = ""


class LineItem(BaseModel):
    item_name: str
    description: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    total_price: float = 0.0
    matched_product_id: str = ""
    is_value_add: bool = False


class PricingStrategy(BaseModel):
    line_items: list[LineItem] = []
    subtotal: float = 0.0
    tax_rate: float = 0.18
    tax_label: str = "GST"
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = "INR"
    competitor_analyses: list[CompetitorAnalysis] = []
    value_adds: list[LineItem] = []
    value_adds_total: float = 0.0
    pricing_rationale: str = ""
    strategy_summary: str = ""


class ProposalSection(BaseModel):
    title: str
    content: str


class ProposalDraft(BaseModel):
    executive_summary: str = ""
    technical_proposal: list[ProposalSection] = []
    project_plan: str = ""
    value_proposition: str = ""
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


class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    rfp_input: Optional[RFPInput] = None
    extracted_requirements: Optional[ExtractedRequirements] = None
    pricing_strategy: Optional[PricingStrategy] = None
    proposal_draft: Optional[ProposalDraft] = None
    pdf_path: Optional[str] = None
    messages: list[AgentMessage] = []
    revision_count: int = 0


from typing import TypedDict

class GraphState(TypedDict, total=False):
    job_id: str
    status: JobStatus
    rfp_input: RFPInput
    extracted_requirements: ExtractedRequirements
    universal_rfp: dict  # Canonical UniversalRFP as JSON-serializable dict
    pricing_strategy: PricingStrategy
    proposal_draft: ProposalDraft
    feedback: HumanFeedback
    pdf_path: str
    messages: list[AgentMessage]
    revision_count: int
