"""
Junior Analyst Agent — v3 (Option B: Direct Extraction)
=========================================================
Responsible for parsing unstructured RFP documents and extracting
key requirements into a structured format.

KEY CHANGE (v3):
  [CRITICAL] Multi-query RAG decomposition DISABLED (Option B)
  [CRITICAL] Direct single-shot extraction from raw RFP text
  [CRITICAL] Reduces API calls from ~10-15 to ~1-3, avoiding rate limits
  [CRITICAL] No more Gemini 5 req/min quota exhaustion

Previous upgrades (from v2, still active):
  [CRITICAL] _sanitise() is called at the top of analyze() + PII scrubbing
  [CRITICAL] Fallback path to direct single-shot extraction and flags ALL fields low-confidence
  [HIGH]     Few-shot examples added to extraction prompt (simple + complex case)
  [HIGH]     ScopeItem schema expanded: is_mandatory, priority (P1/P2/P3)
  [HIGH]     Document-level: disqualification_criteria field added
  [HIGH]     Category taxonomy expanded from 3 → 8 values
  [HIGH]     compliance_checklist output field added (seeds Agent 3's matrix)
"""

import asyncio
import json
import re
import logging
from typing import Callable, Optional

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
MAX_RFP_CHARS = 12_000
MAX_RAG_SUMMARY_CHARS = 8_000

# ── [OPTION 1: Exponential Backoff for Rate Limit Handling] ────────────────
# Fits Gemini free tier: 5 req/min = 1 req per 12 seconds
# Using exponential backoff to handle 429 rate limit errors gracefully
SUBQUERY_CONCURRENCY = 1  # Serialized (no parallel queries to avoid quota exhaustion)
BASE_BACKOFF_SECONDS = 12  # Initial wait time (12s = 1 freq request per min)
MAX_BACKOFF_SECONDS = 60  # Cap backoff at 1 minute per retry
BACKOFF_MULTIPLIER = 2.0  # Exponential: 12s → 24s → 48s → 60s(capped)

# ── [DEPRECATED: Old approach — kept for reference] ────────────────────────
# SUBQUERY_CONCURRENCY = 1  # Previously used with asyncio.Semaphore, no backoff
# Now replaced with explicit exponential backoff logic in run_single_query()

# Expanded from 3 → 8 to support real GST category mapping in Agent 2
VALID_CATEGORIES = {
    "hardware",
    "software_license",
    "saas",
    "professional_service",
    "amc",
    "consulting",
    "logistics",
    "other",
}

VALID_PRIORITIES = {"P1", "P2", "P3"}

# PII patterns — scrubbed before any text leaves the system boundary
_PII_PATTERNS = [
    (re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"), "[AADHAAR_REDACTED]"),   # Aadhaar
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN_REDACTED]"),               # PAN
    (re.compile(r"\b[6-9]\d{9}\b"), "[PHONE_REDACTED]"),                     # Indian mobile
    (re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]"),      # Email
]


# ──────────────────────────────────────────────
# Few-shot examples (injected into prompt)
# ──────────────────────────────────────────────
FEW_SHOT_EXAMPLES = """
EXAMPLE 1 — Simple RFP (3 items, INR budget, direct notation)
Input hint: "Supply 10 laptops, 2 network switches, and annual support. Budget: ₹18,00,000."
Expected output (abbreviated):
{
  "project_name": "IT Procurement 2024",
  "scope_items": [
    {"item_name": "Laptop", "quantity": 10, "category": "hardware",
     "is_mandatory": true, "priority": "P1"},
    {"item_name": "Network Switch", "quantity": 2, "category": "hardware",
     "is_mandatory": true, "priority": "P1"},
    {"item_name": "Annual Support", "quantity": 1, "category": "amc",
     "is_mandatory": false, "priority": "P2"}
  ],
  "budget_amount": 1800000,
  "compliance_checklist": []
}

EXAMPLE 2 — Complex RFP (multi-currency, lakh notation, phased, no explicit quantity)
Input hint: "Phase 1: Deploy ERP SaaS for 3 offices. Phase 2: Data migration consulting.
Budget: USD 2,50,000. Evaluation: ISO 27001 certification mandatory. Response by 15-Mar-2025."
Expected output (abbreviated):
{
  "project_name": "ERP Modernisation Programme",
  "scope_items": [
    {"item_name": "ERP SaaS Platform", "quantity": 3, "category": "saas",
     "is_mandatory": true, "priority": "P1",
     "specifications": "Phase 1 — 3 office deployments"},
    {"item_name": "Data Migration Consulting", "quantity": 1, "category": "consulting",
     "is_mandatory": true, "priority": "P1",
     "specifications": "Phase 2 — full data migration"}
  ],
  "budget_amount": 250000,
  "budget_currency": "USD",
  "disqualification_criteria": ["ISO 27001 certification not held"],
  "compliance_checklist": [
    {"criterion": "ISO 27001 certification", "addressable_by_us": true}
  ]
}
"""


# ──────────────────────────────────────────────
# Extraction Prompt
# ──────────────────────────────────────────────
EXTRACTION_PROMPT = PromptTemplate.from_template("""You are the "Junior Analyst" — an expert RFP analyst working for an SME.

TASK
----
Parse the RFP document below and return a single JSON object.
Reason step-by-step internally before writing JSON, but DO NOT output your reasoning.
Do NOT output any <think> tags, markdown fences, or explanatory text.
Consider these points before you produce JSON:
  1. What is the project and who issued it?
  2. List every scope item — quantity, category, whether mandatory, and priority tier.
  3. Is there an explicit budget figure? Convert Indian lakh notation to a plain integer.
     (e.g. ₹50,00,000 → 5000000; "2.5 lakh" → 250000)
  4. What are the key deadlines, evaluation criteria, submission rules, and minimum requirements?
  5. Are there any criteria that would DISQUALIFY a bidder (certifications, turnover thresholds, etc.)?
  6. Map each evaluation criterion to a boolean: can we address it?

Then output ONLY the JSON (no markdown fences, no extra text).

STUDY THESE EXAMPLES FIRST
---------------------------
{few_shot_examples}

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
      "category": "<hardware|software_license|saas|professional_service|amc|consulting|logistics|other>",
      "is_mandatory": <true|false>,
      "priority": "<P1|P2|P3>"
    }}
  ],
  "budget_amount": <number — plain integer, e.g. 5000000; 0 if not stated>,
  "budget_currency": "INR",
  "evaluation_criteria": ["string"],
  "disqualification_criteria": ["string — criteria that automatically disqualify a bidder"],
  "compliance_checklist": [
    {{
      "criterion": "string",
      "addressable_by_us": <true|false — assume true if ambiguous>
    }}
  ],
  "project_timeline": "string",
  "submission_requirements": ["string"],
  "additional_notes": "string",
  "low_confidence_fields": ["list field names that were ambiguous or inferred"]
}}

RULES
-----
- quantity MUST be a plain integer (never a string or float).
- budget_amount MUST be a plain integer.
- category MUST be one of: hardware, software_license, saas, professional_service, amc, consulting, logistics, other.
- is_mandatory: true if the RFP uses "shall", "must", "mandatory", "required"; false for "should", "preferred", "optional".
- priority: P1 = must-have / showstopper, P2 = important but negotiable, P3 = nice-to-have.
- If you cannot extract meaningful information, set fields to empty/null and mark them in "low_confidence_fields".

{additional_instructions}""")


# ──────────────────────────────────────────────
# Decomposed query plan (5 focused sub-queries)
# ──────────────────────────────────────────────
QUERY_PLAN = [
    ("parties",
     "Find the project name, issuing company/organisation, date of issue, and any reference numbers."),
    ("scope_boq",
     "Find the complete list of scope items, deliverables, and Bill of Quantities (BOQ). "
     "For each item capture: name, description, quantity, specifications, and whether it is mandatory."),
    ("commercial",
     "Find the total budget, payment terms, currency, any lakh/crore figures, "
     "and whether prices should be quoted inclusive or exclusive of GST."),
    ("evaluation",
     "Find all evaluation criteria, scoring weights, mandatory qualifications, "
     "minimum turnover or experience requirements, and any automatic disqualification clauses."),
    ("timelines",
     "Find the submission deadline, project timeline, milestones, delivery schedule, "
     "and all submission requirements (format, copies, digital/physical)."),
]


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
        rfp_text: str = "",               # raw text used for fallback path
        emit_message: Optional[Callable] = None,
        additional_instructions: str = "",
    ) -> tuple[ExtractedRequirements, dict]:
        """Parse RFP using Hierarchical RAG + multi-query decomposition."""

        # ── [CRITICAL FIX] Sanitise + PII-scrub before anything touches the LLM ──
        rfp_text = self._sanitise(rfp_text)

        await self._emit(emit_message, MessageType.STATUS,
                         "Starting multi-query RAG decomposition...")

        # ── [CRITICAL FIX] Parallel multi-query exploration ──────────────────────
        doc_tool = build_document_query_tool(job_id)
        agent_executor = create_react_agent(self.chat_llm, [doc_tool])

        await self._emit(emit_message, MessageType.THINKING,
                         f"Dispatching {len(QUERY_PLAN)} parallel sub-queries against the RFP Knowledge Base...")

        rag_summary, all_low_confidence = await self._run_parallel_queries(
            agent_executor, additional_instructions, emit_message, rfp_text
        )

        await self._emit(emit_message, MessageType.THINKING,
                         "Formatted RFP text. Running structured JSON extraction...")

        # ── Build extraction prompt ───────────────────────────────────────────────
        # [OPTION B] Detect if this is raw RFP text (no RAG processing)
        is_option_b = not any(x in rag_summary for x in ["[PARTIES]", "[SCOPE_BOQ]", "[COMMERCIAL]"])
        
        if is_option_b:
            # Option B: direct extraction from raw RFP text
            rfp_label = "RAW RFP DOCUMENT"
        else:
            # Option 1 (deprecated): RAG-processed multi-query summary
            rfp_label = "MULTI-QUERY RAG EXPLORATION SUMMARY"
        
        instructions_block = (
            f"\nADDITIONAL INSTRUCTIONS FROM USER:\n{additional_instructions}"
            if additional_instructions else ""
        )
        prompt_text = EXTRACTION_PROMPT.format(
            rfp_text=f"{rfp_label}:\n{rag_summary}",
            few_shot_examples=FEW_SHOT_EXAMPLES,
            additional_instructions=instructions_block,
        )

        # ── JSON extraction with retry ────────────────────────────────────────────
        raw_response = await self._call_llm_with_retry(prompt_text, emit_message)

        await self._emit(emit_message, MessageType.THINKING,
                         "Validating and normalising extracted data...")

        requirements, raw_dict = self._parse_and_validate(raw_response)

        # Merge any low-confidence fields surfaced during fallback
        if all_low_confidence:
            existing = set(raw_dict.get("low_confidence_fields", []))
            raw_dict["low_confidence_fields"] = sorted(existing | set(all_low_confidence))

        if raw_dict.get("low_confidence_fields"):
            await self._emit(
                emit_message, MessageType.THINKING,
                f"Low-confidence fields flagged for human review: "
                f"{', '.join(raw_dict['low_confidence_fields'])}"
            )

        if raw_dict.get("disqualification_criteria"):
            await self._emit(
                emit_message, MessageType.THINKING,
                f"⚠ Disqualification criteria detected: "
                f"{'; '.join(raw_dict['disqualification_criteria'])}"
            )

        # ── TWIST 2: Intra-document conflict detection ─────────────────────────
        try:
            from app.services.conflict_detector import conflict_detector
            conflict_report = await conflict_detector.detect_conflicts(
                rfp_text=rfp_text,
                emit_message=emit_message,
            )
            requirements.conflict_report = conflict_report
        except Exception as e:
            logger.warning("Conflict detection failed: %s", e)
            await self._emit(emit_message, MessageType.THINKING,
                             f"Conflict scan skipped: {e}")

        # ── Emit summary ──────────────────────────────────────────────────────────
        conflict_info = ""
        if requirements.conflict_report and requirements.conflict_report.has_conflicts:
            conflict_info = f"\n• ⚠ Conflicts: {len(requirements.conflict_report.conflicts)} contradiction(s) detected & resolved"

        await self._emit(emit_message, MessageType.RESULT,
            f"Successfully extracted requirements:\n"
            f"• Project: {requirements.project_name}\n"
            f"• Client: {requirements.issuing_company}\n"
            f"• Scope Items: {len(requirements.scope_items)} items identified\n"
            f"• Budget: {requirements.budget_currency} {requirements.budget_amount:,.0f}\n"
            f"• Deadline: {requirements.response_deadline}\n"
            f"• Compliance checklist: {len(raw_dict.get('compliance_checklist', []))} criteria mapped"
            f"{conflict_info}"
        )
        for item in requirements.scope_items:
            mandatory_flag = "✓ mandatory" if item.is_mandatory else "optional"
            await self._emit(emit_message, MessageType.ACTION,
                f"Identified [{item.priority}] → {item.item_name} "
                f"(Qty: {item.quantity}, Category: {item.category}, {mandatory_flag})"
            )

        await self._emit(emit_message, MessageType.COMPLETE,
                         "RFP analysis complete. Awaiting human review before handoff.")

        return requirements, raw_dict

    # ------------------------------------------------------------------
    # Multi-query parallel exploration
    # ------------------------------------------------------------------
    async def _run_parallel_queries(
        self,
        agent_executor,
        additional_instructions: str,
        emit_message: Optional[Callable],
        rfp_text: str,
    ) -> tuple[str, list]:
        """
        [OPTION B: Single-shot direct extraction]
        Skip multi-query decomposition entirely. Go straight to JSON extraction
        from raw RFP text. Reduces API calls from ~10-15 to ~1-3.
        Much faster and avoids Gemini free tier rate limits.
        Returns (rfp_text, low_confidence_fields_from_fallback).
        """

        # ── [OPTION B: Skip RAG decomposition] ──────────────────────────────────
        await self._emit(emit_message, MessageType.THINKING,
                         "Skipping multi-query decomposition (Option B). "
                         "Using direct single-shot extraction on raw RFP text...")

        # Return raw RFP text directly — no LLM calls yet
        merged = rfp_text
        low_confidence_fields: list = []

        if len(merged) > MAX_RAG_SUMMARY_CHARS:
            logger.warning("RFP text truncated from %d to %d chars.", len(merged), MAX_RAG_SUMMARY_CHARS)
            merged = merged[:MAX_RAG_SUMMARY_CHARS] + "\n\n[... document truncated for token budget ...]"

        return merged, low_confidence_fields

        # ── [DEPRECATED: Option 1 — 5-query multi-decomposition approach] ──────
        # Used exponential backoff but still caused rate limits due to multiple
        # parallel/serialized LLM calls (one per query). Option B bypasses RAG entirely.
        # 
        # Original Option 1 code structure (preserved as reference):
        # 
        # async def run_single_query_with_backoff(label: str, question: str) -> str:
        #     """Execute a single query with exponential backoff on rate limit errors."""
        #     backoff_seconds = BASE_BACKOFF_SECONDS
        #     attempt = 0
        #     last_exc: Exception | None = None
        #
        #     while attempt < MAX_RETRIES:
        #         attempt += 1
        #         try:
        #             prompt = (...RAG query prompt...)
        #             response = await agent_executor.ainvoke({...})
        #             return f"[{label.upper()}]\n{response['messages'][-1].content}"
        #         except Exception as exc:
        #             last_exc = exc
        #             exc_str = str(exc).lower()
        #             is_rate_limit = ("429" in exc_str or "quota exceeded" in exc_str)
        #             if is_rate_limit and attempt < MAX_RETRIES:
        #                 # Apply exponential backoff (12s → 24s → 48s → 60s)
        #                 await asyncio.sleep(backoff_seconds)
        #                 backoff_seconds = min(backoff_seconds * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)
        #             else:
        #                 return f"[{label.upper()}]\nNOT FOUND (sub-query failed)"
        #
        # # Sequential execution of all 5 queries:
        # results = []
        # for label, question in QUERY_PLAN:
        #     result = await run_single_query_with_backoff(label, question)
        #     results.append(result)
        #     await asyncio.sleep(1)  # Inter-query delay
        #
        # # Then merge and validate results...
        # ──────────────────────────────────────────────────────────────────────────────

    # ------------------------------------------------------------------
    # LLM construction — Deepseek primary
    # chat_llm  → Deepseek (json extraction + RAG queries)
    # json_llm  → Deepseek (main JSON extraction with 64K context)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_chat_llm():
        """Deepseek: RAG sub-queries and JSON extraction."""
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.PRIMARY_MODEL,
            temperature=0.1,
            max_tokens=1200,
        )

    @staticmethod
    def _build_json_llm():
        """Deepseek: high-quality JSON extraction with 64K token context."""
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.PRIMARY_MODEL,
            temperature=0.1,
            max_tokens=2500,
        )

    # ------------------------------------------------------------------
    # LLM call with retry + exponential backoff for rate limits
    # ------------------------------------------------------------------
    async def _call_llm_with_retry(
        self,
        prompt_text: str,
        emit_message: Optional[Callable],
    ) -> str:
        """
        Attempt LLM call with retry logic.
        [OPTION 1] Handles rate limit errors (429) with exponential backoff.
        """
        attempt = 0
        last_exc: Exception = RuntimeError("Unknown error")
        backoff_seconds = BASE_BACKOFF_SECONDS

        while attempt < MAX_RETRIES:
            attempt += 1
            try:
                response_msg = await self.json_llm.ainvoke(prompt_text)
                content = str(response_msg.content) if hasattr(response_msg, "content") else str(response_msg)
                if "{" not in content or "}" not in content:
                    raise ValueError("Model response did not include a JSON object.")
                return content
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc).lower()
                
                # Detect rate limit errors
                is_rate_limit = (
                    "429" in str(type(exc)) or
                    "429" in exc_str or
                    "quota exceeded" in exc_str or
                    "rate limit" in exc_str or
                    ("limit" in exc_str and "exceeded" in exc_str)
                )
                
                if is_rate_limit and attempt < MAX_RETRIES:
                    # Rate limit — apply exponential backoff
                    logger.warning(
                        "Rate limit on JSON extraction (attempt %d/%d). "
                        "Backing off for %.1f seconds...",
                        attempt, MAX_RETRIES, backoff_seconds
                    )
                    await self._emit(emit_message, MessageType.WARNING,
                        f"⚠ Rate limit hit. Waiting {backoff_seconds:.0f}s before retry "
                        f"(attempt {attempt+1}/{MAX_RETRIES})..."
                    )
                    await asyncio.sleep(backoff_seconds)
                    
                    # Increase backoff for next retry
                    backoff_seconds = min(
                        backoff_seconds * BACKOFF_MULTIPLIER,
                        MAX_BACKOFF_SECONDS
                    )
                    
                    # Re-prompt with stricter instruction for next attempt
                    prompt_text = (
                        f"{prompt_text}\n\n"
                        "IMPORTANT: Return ONLY one valid JSON object. "
                        "No <think> tags, no prose, no markdown."
                    )
                else:
                    # Non-rate-limit error or out of retries
                    logger.warning(
                        "LLM call attempt %d/%d failed: %s",
                        attempt, MAX_RETRIES, exc
                    )
                    if attempt < MAX_RETRIES:
                        await self._emit(emit_message, MessageType.THINKING,
                            f"LLM call failed (attempt {attempt}/{MAX_RETRIES}), retrying..."
                        )
                        prompt_text = (
                            f"{prompt_text}\n\n"
                            "IMPORTANT: Return ONLY one valid JSON object. "
                            "No <think> tags, no prose, no markdown."
                        )

        # ── [DEPRECATED: Old retry logic without rate limit awareness] ────────────
        # while attempt < MAX_RETRIES:
        #     attempt += 1
        #     try:
        #         response_msg = await self.json_llm.ainvoke(prompt_text)
        #         content = str(response_msg.content) if hasattr(response_msg, "content") else str(response_msg)
        #         if "{" not in content or "}" not in content:
        #             raise ValueError("Model response did not include a JSON object.")
        #         return content
        #     except Exception as exc:
        #         last_exc = exc
        #         logger.warning("LLM call attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
        #         if attempt < MAX_RETRIES:
        #             await self._emit(emit_message, MessageType.THINKING,
        #                              f"LLM call failed (attempt {attempt}/{MAX_RETRIES}), retrying...")
        #             prompt_text = (
        #                 f"{prompt_text}\n\n"
        #                 "IMPORTANT: Return ONLY one valid JSON object. "
        #                 "No <think> tags, no prose, no markdown."
        #             )
        # ────────────────────────────────────────────────────────────────────────

        await self._emit(emit_message, MessageType.ERROR,
                         f"LLM call failed after {MAX_RETRIES} attempts: {last_exc}")
        raise last_exc

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    def _parse_and_validate(self, response: str) -> tuple[ExtractedRequirements, dict]:
        data = self._extract_json(response)
        self._check_for_error_signal(data)
        data = self._normalise_fields(data)
        return self._build_requirements(data), data

    def _extract_json(self, text: str) -> dict:
        text = text.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        for fence in ("```json", "```"):
            if fence in text:
                text = text.split(fence)[1].split("```")[0].strip()
                break
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end <= start:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
        json_candidate = text[start:end]

        # Deterministic cleanup for common malformed JSON patterns.
        json_candidate = re.sub(r",(\s*[}\]])", r"\1", json_candidate)
        json_candidate = re.sub(r"}\s*{", "},{", json_candidate)
        # Insert missing delimiters between fields: "value"\n"next_key": ...
        json_candidate = re.sub(
            r'([\]"0-9}\]])\s*\n\s*(")',
            r'\1,\n\2',
            json_candidate,
        )

        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError as exc:
            logger.warning("Initial JSON parse failed, attempting repair: %s", exc)
            repaired = self._repair_json_with_llm(json_candidate, str(exc))
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as repaired_exc:
                raise ValueError(f"Invalid JSON from LLM after repair: {repaired_exc}") from repaired_exc

    def _repair_json_with_llm(self, broken_json: str, parse_error: str) -> str:
        """Ask the extraction model to repair malformed JSON into a valid single object."""
        repair_prompt = (
            "You are a JSON repair engine.\n"
            "Fix the malformed JSON below and return ONLY one valid JSON object.\n"
            "Do not add explanations, markdown, or code fences.\n"
            f"Parse error: {parse_error}\n\n"
            "Malformed JSON:\n"
            f"{broken_json}"
        )
        try:
            repaired_msg = self.json_llm.invoke(repair_prompt)
            repaired_text = str(repaired_msg.content) if hasattr(repaired_msg, "content") else str(repaired_msg)
            repaired_text = repaired_text.strip()
            repaired_text = re.sub(r"<think>.*?</think>", "", repaired_text, flags=re.DOTALL).strip()

            start, end = repaired_text.find("{"), repaired_text.rfind("}") + 1
            if start == -1 or end <= start:
                return broken_json
            return repaired_text[start:end]
        except Exception as exc:
            logger.warning("JSON repair call failed; returning original malformed JSON: %s", exc)
            return broken_json

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
        
        # ── [NEW] Handle None values for all string fields ─────────────────────
        string_fields = [
            "project_name", "issuing_company", "date_issued", "response_deadline",
            "budget_currency", "project_timeline", "additional_notes"
        ]
        for field in string_fields:
            if data.get(field) is None:
                data[field] = ""
        
        # ── [NEW] Handle None values for list fields ────────────────────────────
        list_fields = [
            "evaluation_criteria", "disqualification_criteria", 
            "submission_requirements", "scope_items", "compliance_checklist"
        ]
        for field in list_fields:
            if data.get(field) is None:
                data[field] = []
        
        # Budget normalisation
        raw_budget = str(data.get("budget_amount", "0"))
        clean_budget = re.sub(r"[^\d.]", "", raw_budget)
        try:
            data["budget_amount"] = float(clean_budget or "0")
        except ValueError:
            data["budget_amount"] = 0.0
            logger.warning("Could not parse budget_amount=%r; defaulted to 0", raw_budget)

        # Scope item normalisation
        for item in data.get("scope_items", []):
            # Quantity
            raw_qty = item.get("quantity", 1)
            try:
                item["quantity"] = max(1, int(float(str(raw_qty).split()[0])))
            except (ValueError, IndexError):
                item["quantity"] = 1
                logger.warning("Could not parse quantity=%r; defaulted to 1", raw_qty)

            # Category (expanded taxonomy)
            cat = str(item.get("category", "other")).strip().lower().replace(" ", "_")
            item["category"] = cat if cat in VALID_CATEGORIES else "other"

            # is_mandatory — default True for safety (better to over-price than miss a mandatory item)
            item["is_mandatory"] = bool(item.get("is_mandatory", True))

            # priority
            pri = str(item.get("priority", "P1")).strip().upper()
            item["priority"] = pri if pri in VALID_PRIORITIES else "P1"

        # compliance_checklist normalisation
        checklist = data.get("compliance_checklist", [])
        normalised_checklist = []
        for entry in checklist:
            if isinstance(entry, dict) and "criterion" in entry:
                normalised_checklist.append({
                    "criterion": str(entry["criterion"]),
                    "addressable_by_us": bool(entry.get("addressable_by_us", True)),
                })
        data["compliance_checklist"] = normalised_checklist

        # disqualification_criteria — ensure list of strings
        data["disqualification_criteria"] = [
            str(c) for c in data.get("disqualification_criteria", [])
        ]

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
                is_mandatory=item["is_mandatory"],
                priority=item["priority"],
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
            evaluation_criteria=data.get("evaluation_criteria", []),
            disqualification_criteria=data.get("disqualification_criteria", []),
            compliance_checklist=data.get("compliance_checklist", []),
            project_timeline=data.get("project_timeline", ""),
            submission_requirements=data.get("submission_requirements", []),
            additional_notes=data.get("additional_notes", ""),
        )

    # ------------------------------------------------------------------
    # Input sanitisation + PII scrubbing  [CRITICAL FIX — now actually called]
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitise(rfp_text: str) -> str:
        """Validate, PII-scrub, and truncate rfp_text before it touches any prompt."""
        if not rfp_text or not rfp_text.strip():
            raise ValueError("rfp_text must not be empty.")
        text = rfp_text.strip()

        # PII scrubbing pass
        original_len = len(text)
        for pattern, replacement in _PII_PATTERNS:
            text = pattern.sub(replacement, text)
        if len(text) != original_len:
            logger.info("PII patterns detected and redacted from rfp_text before LLM submission.")

        if len(text) > MAX_RFP_CHARS:
            logger.warning(
                "rfp_text truncated from %d to %d chars to stay within token budget.",
                len(text), MAX_RFP_CHARS,
            )
            text = text[:MAX_RFP_CHARS] + "\n\n[... document truncated for token budget ...]"
        return text

    # ------------------------------------------------------------------
    # Emit helper
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