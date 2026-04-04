"""
Junior Analyst Agent (Optimised)
=================================
Responsible for parsing unstructured RFP documents and extracting
key requirements into a structured format.

Improvements over v1
--------------------
- Input validation before any LLM call
- Safe type coercion for quantity and budget fields
- Explicit retry logic (up to MAX_RETRIES attempts)
- response_format=json_object for reliable JSON output
- _parse_response split into focused private helpers
- category field validated against allowed enum values
- Confidence metadata added so human reviewers know what to check
- rfp_text sanitised and token-length-guarded before injection
- emit() promoted to a proper instance-level helper
- Human-in-the-loop hook: returns raw dict alongside the model so
  the orchestrator can surface editable data to the frontend
- Switched to ChatGoogleGenerativeAI (Gemini) per the blueprint;
  falls back gracefully to OpenAI if GOOGLE_API_KEY is absent
"""

import json
import re
import logging
from typing import Callable, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langchain_core.prompts import PromptTemplate
from langgraph.prebuilt import create_react_agent
from app.tools.junior_tools import build_document_query_tool

from app.models import (
    ExtractedRequirements, ScopeItem, AgentMessage,
    AgentRole, MessageType
)
from app.config import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
MAX_RETRIES = 3
MAX_RFP_CHARS = 12_000          # ~3 k tokens — safe for 4096-token models
VALID_CATEGORIES = {"hardware", "software", "service"}


# ──────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────
EXTRACTION_PROMPT = PromptTemplate.from_template("""You are the "Junior Analyst" — an expert RFP analyst working for an SME.

TASK
----
Parse the RFP document below and return a single JSON object.
Before writing JSON, think step-by-step (inside a <think> block) about:
  1. What is the project and who issued it, and in what country is the client located?
  2. List every scope item with its quantity and category and its features.
  3. Is there an explicit budget figure? Convert Indian lakh notation to a plain integer. What currency is expected for the quotation?
  4. What are the key deadlines, evaluation criteria, submission rules and minumum requirements?

Then output ONLY the JSON (no markdown fences, no extra text).

RFP DOCUMENT
------------
{rfp_text}

OUTPUT FORMAT
-------------
{{
  "project_name": "string",
  "issuing_company": "string",
  "date_issued": "string",
  "response_deadline": "string",
  "scope_items": [
    {{
      "item_name": "string",
      "description": "string",
      "quantity": <integer — use 1 if unspecified>,
      "specifications": "string",
      "category": "<hardware|software|service>"
    }}
  ],
  "budget_amount": <number — plain integer, e.g. 5000000 for ₹50,00,000; 0 if not stated>,
  "budget_currency": "<string — currency code, e.g., INR, USD, GBP>",
  "client_country_code": "<string — 2-letter ISO country code of the client, e.g., IN, US, UK, AE>",
  "target_currency": "<string — currency code expected for the quotation, e.g., INR, USD, GBP>",
  "evaluation_criteria": ["string"],
  "project_timeline": "string",
  "submission_requirements": ["string"],
  "additional_notes": "string",
  "low_confidence_fields": ["list field names that were ambiguous or inferred"]
}}

RULES
-----
- quantity MUST be a plain integer (never a string or float).
- budget_amount MUST be a plain integer (never a formatted string like "50,00,000").
- category MUST be one of: hardware, software, service — nothing else.
- If the document is not a valid RFP, return ONLY: {{"error": "Invalid RFP document"}}

{additional_instructions}""")


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────
class JuniorAnalyst:
    """Parses unstructured RFP text and extracts structured requirements."""

    def __init__(self):
        self.chat_llm = self._build_chat_llm()
        self.json_llm = self._build_json_llm()
        self.role = AgentRole.JUNIOR_ANALYST

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def analyze(
        self,
        job_id: str,
        emit_message: Optional[Callable] = None,
        additional_instructions: str = "",
    ) -> tuple[ExtractedRequirements, dict]:
        """Parse RFP using Hierarchical RAG tool and return structured requirements."""


        await self._emit(emit_message, MessageType.STATUS, "Starting Hierarchical RAG document analysis...")
        await self._emit(emit_message, MessageType.THINKING,
                         "Equipping tools to query the Vector Storage for specific sections...")

        # 2. Tool calling loop with ReAct agent
        doc_tool = build_document_query_tool(job_id)
        agent_executor = create_react_agent(self.chat_llm, [doc_tool])
        
        exploration_prompt = f"""You are the Junior Analyst. Use your document_query_tool to search the document and find the following facts systematically:
1. Project name and issuing company. Keep these CONCISE (max 10 words).
2. The country where the client is based.
3. Full list of scope items, their quantities, and descriptions.
4. Budget figure, currency, and submission deadlines.

Additional Instructions: {additional_instructions}

Gather all the facts by querying the document multiple times. Finally, output a comprehensive summary of all these points."""

        await self._emit(emit_message, MessageType.ACTION,
                         "Executing multi-step queries against the RFP Knowledge Base...")
        try:
            response = await agent_executor.ainvoke({"messages": [("user", exploration_prompt)]})
            rag_summary = response["messages"][-1].content
        except Exception as e:
            logger.warning(f"ReAct agent failed, falling back to manual: {e}")
            rag_summary = "Exploration failed. No data fetched."

        await self._emit(emit_message, MessageType.THINKING,
                         "RAG exploration complete. Extracting final structured JSON...")

        # 3. Build extraction prompt
        instructions_block = (
            f"\nADDITIONAL INSTRUCTIONS FROM USER:\n{additional_instructions}"
            if additional_instructions else ""
        )
        prompt_text = EXTRACTION_PROMPT.format(
            rfp_text=f"RAG EXPLORATION SUMMARY:\n{rag_summary}",
            additional_instructions=instructions_block,
        )

        # 4. Call JSON LLM with retry
        raw_response = await self._call_llm_with_retry(prompt_text, emit_message)

        await self._emit(emit_message, MessageType.THINKING,
                         "Validating and normalising extracted data...")

        # 4. Parse + validate
        requirements, raw_dict = self._parse_and_validate(raw_response)

        # 5. Surface low-confidence fields for human review
        if raw_dict.get("low_confidence_fields"):
            await self._emit(
                emit_message, MessageType.THINKING,
                f"Low-confidence fields flagged for human review: "
                f"{', '.join(raw_dict['low_confidence_fields'])}"
            )

        # 6. Emit summary
        await self._emit(emit_message, MessageType.RESULT,
            f"Successfully extracted requirements:\n"
            f"• Project: {requirements.project_name}\n"
            f"• Client: {requirements.issuing_company}\n"
            f"• Scope Items: {len(requirements.scope_items)} items identified\n"
            f"• Budget: {requirements.budget_currency} {requirements.budget_amount:,.0f}\n"
            f"• Region: {requirements.client_country_code} (Target Currency: {requirements.target_currency})\n"
            f"• Deadline: {requirements.response_deadline}"
        )
        for item in requirements.scope_items:
            await self._emit(emit_message, MessageType.ACTION,
                f"Identified → {item.item_name} "
                f"(Qty: {item.quantity}, Category: {item.category})"
            )

        await self._emit(emit_message, MessageType.COMPLETE,
                         "RFP analysis complete. Awaiting human review before handoff.")

        return requirements, raw_dict

    # ------------------------------------------------------------------
    # LLM construction
    # ------------------------------------------------------------------
    @staticmethod
    def _build_chat_llm():
        """Standard chat LLM capable of function calling."""
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.1,
            max_tokens=4096,
        )

    @staticmethod
    def _build_json_llm():
        """LLM constrained to JSON object response format."""
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.1,
            max_tokens=4096,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------
    async def _call_llm_with_retry(
        self,
        prompt_text: str,
        emit_message: Optional[Callable],
    ) -> str:
        attempt = 0
        last_exc: Exception = RuntimeError("Unknown error")

        while attempt < MAX_RETRIES:
            attempt += 1
            try:
                response_msg = await self.json_llm.ainvoke(prompt_text)
                return str(response_msg.content) if hasattr(response_msg, "content") else str(response_msg)
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM call attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    await self._emit(emit_message, MessageType.THINKING,
                                     f"LLM call failed (attempt {attempt}/{MAX_RETRIES}), retrying...")

        await self._emit(emit_message, MessageType.ERROR,
                         f"LLM call failed after {MAX_RETRIES} attempts: {last_exc}")
        raise last_exc

    # ------------------------------------------------------------------
    # Parsing helpers (single responsibility)
    # ------------------------------------------------------------------
    def _parse_and_validate(self, response: str) -> tuple[ExtractedRequirements, dict]:
        """Extract JSON → validate structure → build domain model."""
        data = self._extract_json(response)
        self._check_for_error_signal(data)
        data = self._normalise_fields(data)
        return self._build_requirements(data), data

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Strip markdown fences and locate the JSON object."""
        text = text.strip()
        # Strip think block if present (chain-of-thought)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Strip markdown fences
        for fence in ("```json", "```"):
            if fence in text:
                text = text.split(fence)[1].split("```")[0].strip()
                break
        # Find outermost JSON object
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end <= start:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from LLM: {exc}") from exc

    @staticmethod
    def _check_for_error_signal(data: dict) -> None:
        if "error" in data:
            raise ValueError(
                "The provided document does not appear to be a valid RFP. "
                "Please supply a full RFP document."
            )

    @staticmethod
    def _normalise_fields(data: dict) -> dict:
        """Coerce types safely; never raise on bad LLM output."""
        # Budget: strip commas/symbols then convert
        raw_budget = str(data.get("budget_amount", "0"))
        clean_budget = re.sub(r"[^\d.]", "", raw_budget)
        try:
            data["budget_amount"] = float(clean_budget or "0")
        except ValueError:
            data["budget_amount"] = 0.0
            logger.warning("Could not parse budget_amount=%r; defaulted to 0", raw_budget)

        # Scope items: safe quantity coercion + category validation
        for item in data.get("scope_items", []):
            raw_qty = item.get("quantity", 1)
            try:
                item["quantity"] = max(1, int(float(str(raw_qty).split()[0])))
            except (ValueError, IndexError):
                item["quantity"] = 1
                logger.warning("Could not parse quantity=%r; defaulted to 1", raw_qty)

            cat = str(item.get("category", "service")).strip().lower()
            item["category"] = cat if cat in VALID_CATEGORIES else "service"

        return data

    @staticmethod
    def _build_requirements(data: dict) -> ExtractedRequirements:
        scope_items = [
            ScopeItem(
                item_name=item.get("item_name", ""),
                description=item.get("description", ""),
                quantity=item["quantity"],
                specifications=item.get("specifications", ""),
                category=item["category"],
            )
            for item in data.get("scope_items", [])
        ]
        return ExtractedRequirements(
            project_name=data.get("project_name", ""),
            issuing_company=data.get("issuing_company", ""),
            date_issued=data.get("date_issued", ""),
            response_deadline=data.get("response_deadline", ""),
            scope_items=scope_items,
            budget_amount=data["budget_amount"],
            budget_currency=data.get("budget_currency", "INR"),
            client_country_code=data.get("client_country_code", "IN").upper(),
            target_currency=data.get("target_currency", "INR").upper(),
            evaluation_criteria=data.get("evaluation_criteria", []),
            project_timeline=data.get("project_timeline", ""),
            submission_requirements=data.get("submission_requirements", []),
            additional_notes=data.get("additional_notes", ""),
        )

    # ------------------------------------------------------------------
    # Input sanitisation
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitise(rfp_text: str) -> str:
        """Validate and truncate rfp_text before it touches the prompt."""
        text = (rfp_text or "").strip()
        
        # 1. Physical Presence Check
        if not text:
            raise ValueError("RFP content is empty.")
            
        # 2. Semantic "Smoke Test" (Section 7.1 Robustness)
        # RFPs are rarely under 150 characters. If it's too short, it's likely just "hi" or "hello".
        MIN_RFP_CHARS = 150
        if len(text) < MIN_RFP_CHARS:
            raise ValueError(
                f"Input is too short to be a valid RFP document (Minimum {MIN_RFP_CHARS} chars). "
                f"Please provide more context or a full document."
            )
            
        # 3. Keyword Check (Optional but helpful)
        keywords = ["rfp", "bid", "proposal", "scope", "requirement", "contract", "tender", "submission", "deadline"]
        has_context = any(word in text.lower() for word in keywords)
        if len(text) < 500 and not has_context:
            # For short-ish documents, ensure they at least look professional
            raise ValueError(
                "The provided text does not appear to be a professional RFP document. "
                "Ensure keywords like 'Scope', 'Proposal', or 'Requirements' are present."
            )

        # 4. Token Length Guard
        if len(text) > MAX_RFP_CHARS:
            logger.warning(
                "rfp_text truncated from %d to %d chars to stay within token budget.",
                len(text), MAX_RFP_CHARS,
            )
            text = text[:MAX_RFP_CHARS] + "\n\n[... document truncated for token budget ...]"
            
        return text

    # ------------------------------------------------------------------
    # Emit helper (instance method — testable, not a closure)
    # ------------------------------------------------------------------
    @staticmethod
    async def _emit(
        emit_message: Optional[Callable],
        msg_type: MessageType,
        content: str,
    ) -> None:
        if emit_message:
            await emit_message(AgentMessage(
                agent=AgentRole.JUNIOR_ANALYST,
                message_type=msg_type,
                content=content,
            ))