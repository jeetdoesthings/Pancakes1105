"""
Senior Copywriter Agent — v2 (Hardened)
=========================================
Drafts professional, persuasive proposal content based on
extracted requirements and pricing strategy.

Upgrades applied (from review):
  [CRITICAL] Single 6000-token monolith replaced with parallel per-section generation
             via asyncio.gather() — each section gets a focused prompt + 1500-token budget,
             independent retry, and can stream to the approval UI as it completes
  [CRITICAL] evaluation_criteria from the RFP are now a mandatory prompt variable in every
             technical section — each section must open by citing which criterion it addresses
  [CRITICAL] Per-section temperature dict replaces the single 0.4 global value:
             executive_summary / value_proposition → 0.35 (persuasive voice)
             technical_* / project_plan → 0.10 (accuracy-first)
             company_profile / support_plan / terms_and_conditions → 0.05 (template verbatim)
  [HIGH]     Compliance matrix generated as a dedicated section seeded from Agent 1's
             compliance_checklist — renders as a table in the PDF
  [HIGH]     Templates fully decoupled from LLM prompts — company_profile, support_plan,
             and terms_and_conditions are filled by pure string substitution; zero LLM
             tokens spent on boilerplate. LLM reserved for 4 creative sections only.
  [HIGH]     Value-add business impact quantification: each value-add gets a
             business_impact_statement computed before any LLM call
  [MEDIUM]   max_words_per_section derived from RFP submission_requirements
  [MEDIUM]   client_profile tone/localisation control:
             public_sector | private_enterprise | startup | international
"""

import asyncio
import json
import logging
import re
from typing import Callable, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

from app.models import (
    ExtractedRequirements, PricingStrategy, ProposalDraft, ProposalSection,
    AgentMessage, AgentRole, MessageType
)
from app.config import settings
from app.tools.copywriter_tools import template_filler_tool

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
MAX_SECTION_RETRIES = 2
DEFAULT_MAX_WORDS = 300   # per section, overridden by RFP submission_requirements

# [CRITICAL] Per-section temperature — never a single global value
SECTION_TEMPERATURES: dict[str, float] = {
    "executive_summary":    0.35,   # Needs persuasive, authoritative voice
    "value_proposition":    0.35,   # Needs compelling, benefit-oriented copy
    "technical_proposal":   0.10,   # Must be accurate; no creative licence
    "project_plan":         0.10,   # Factual milestone sequencing
    # Boilerplate sections — filled by template substitution, temperature unused
    "company_profile":      0.05,
    "support_plan":         0.05,
    "terms_and_conditions": 0.05,
}

# [MEDIUM] Client profile → tone instructions injected into every prompt
CLIENT_PROFILE_TONES: dict[str, str] = {
    "public_sector": (
        "Use formal, regulatory-compliant language. Reference standards (ISO, BIS, GFR) "
        "where relevant. Avoid colloquialisms. Prefer passive voice for procedural descriptions."
    ),
    "private_enterprise": (
        "Use confident, ROI-focused language. Lead with business outcomes, not technical specs. "
        "Be direct and commercially astute."
    ),
    "startup": (
        "Use direct, outcome-oriented language. Avoid corporate jargon. "
        "Emphasise speed, flexibility, and partnership over process."
    ),
    "international": (
        "Use globally neutral professional English. Avoid India-specific idioms, "
        "currency symbols other than the agreed billing currency, and local regulatory references "
        "unless they are directly relevant to the client's jurisdiction."
    ),
}

# ──────────────────────────────────────────────
# Section-level prompts (each is focused and tight)
# ──────────────────────────────────────────────

EXEC_SUMMARY_PROMPT = PromptTemplate.from_template("""You are a Senior Proposal Writer for {company_name}.

Write a compelling EXECUTIVE SUMMARY for the following proposal.
Limit: {max_words} words.
Tone instruction: {tone_instruction}

PROJECT: {project_name}
CLIENT: {issuing_company}
KEY EVALUATION CRITERIA (the client will score against these — address all of them):
{evaluation_criteria}

OUR PRICING APPROACH: {strategy_summary}
VALUE-ADDS WITH BUSINESS IMPACT:
{enriched_value_adds}

Instructions:
- Open by demonstrating you understand the client's core business problem.
- In paragraph 2, assert why {company_name} is uniquely positioned to deliver.
- In paragraph 3, reference the win-probability context and our differentiation.
- Do NOT name competitors. Do NOT use placeholder text.
- Write {max_words} words or fewer. Return plain prose, no JSON, no headers.""")

TECHNICAL_SECTION_PROMPT = PromptTemplate.from_template("""You are a Senior Technical Proposal Writer for {company_name}.

Write the TECHNICAL PROPOSAL SECTION for the line item below.
Limit: {max_words} words.
Tone instruction: {tone_instruction}

LINE ITEM: {item_name}
DESCRIPTION: {item_description}
QUANTITY: {quantity}
SPECIFICATIONS: {specifications}
CATEGORY: {category}
IS MANDATORY: {is_mandatory}
PRIORITY TIER: {priority}

RFP EVALUATION CRITERIA (open your section by citing which criterion this item addresses):
{evaluation_criteria}

Instructions:
- First sentence MUST cite which evaluation criterion this item satisfies.
- Describe what we are supplying, why it meets the specification, and any relevant standards.
- Reference quantity and any volume or configuration considerations.
- Be factually precise. No marketing filler. Return plain prose.""")

PROJECT_PLAN_PROMPT = PromptTemplate.from_template("""You are a Senior Project Planner for {company_name}.

Write a DETAILED PROJECT PLAN section for the following engagement.
Limit: {max_words} words.
Tone instruction: {tone_instruction}

PROJECT TIMELINE FROM RFP: {project_timeline}
SUBMISSION DEADLINE: {response_deadline}
SCOPE ITEM COUNT: {scope_item_count}
SCOPE CATEGORIES: {scope_categories}

RFP EVALUATION CRITERIA:
{evaluation_criteria}

Instructions:
- Break the plan into named phases (e.g., Mobilisation, Delivery, Testing, Handover, BAU).
- Each phase must have a duration and key milestone.
- At least one phase must explicitly reference how it satisfies an evaluation criterion.
- Return plain prose with phase headers (e.g., "Phase 1 — Mobilisation (Week 1–2):").
- {max_words} words or fewer.""")

VALUE_PROP_PROMPT = PromptTemplate.from_template("""You are a Senior Copywriter for {company_name}.

Write a powerful VALUE PROPOSITION section.
Limit: {max_words} words.
Tone instruction: {tone_instruction}

WIN PROBABILITY SCORE: {win_probability_score}/100
PRICING STRATEGY: {strategy_summary}

VALUE-ADDS WITH QUANTIFIED BUSINESS IMPACT:
{enriched_value_adds}

COMPETITOR POSITION:
{competitor_position_summary}

Instructions:
- Lead with the client's risk, not our features.
- For EACH value-add, use the pre-computed business_impact_statement to frame the benefit
  in monetary or time terms (e.g. "eliminates ₹X in Year 1 maintenance risk").
- Do NOT use generic phrases like "we are committed to excellence."
- Close with a one-sentence call to action.
- Return plain prose, {max_words} words or fewer.""")


class SeniorCopywriter:
    """Drafts professional proposal content using parallel section generation."""

    def __init__(self):
        # [CRITICAL] Base LLM — temperature overridden per section via _make_llm()
        self._llm_cache: dict[float, ChatOpenAI] = {}
        self.role = AgentRole.SENIOR_COPYWRITER

    # ------------------------------------------------------------------
    # LLM factory — one instance per temperature, cached
    # ------------------------------------------------------------------
    def _make_llm(self, temperature: float, max_tokens: int = 1500) -> ChatOpenAI:
        """
        Deepseek for all sections (persuasive and structured).
        Instances are cached per temperature key.
        """
        key = round(temperature, 2)
        if key not in self._llm_cache:
            self._llm_cache[key] = ChatOpenAI(
                base_url=settings.DEEPSEEK_BASE_URL,
                api_key=settings.DEEPSEEK_API_KEY,
                model=settings.PRIMARY_MODEL,
                temperature=key,
                max_tokens=max_tokens,
            )
        return self._llm_cache[key]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def draft(
        self,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        company_name: str = "Ering Solutions",
        client_profile: str = "private_enterprise",   # [MEDIUM]
        emit_message: Optional[Callable] = None,
        additional_instructions: str = "",
    ) -> ProposalDraft:
        """Draft professional proposal content via parallel section generation."""

        async def emit(msg_type: MessageType, content: str):
            if emit_message:
                await emit_message(AgentMessage(
                    agent=self.role,
                    message_type=msg_type,
                    content=content,
                ))

        await emit(MessageType.STATUS, "Starting parallel proposal section drafting...")

        # ── [MEDIUM] Derive word budget from RFP submission requirements ──────────
        max_words = self._derive_word_budget(requirements.submission_requirements)

        # ── [MEDIUM] Tone instruction from client profile ─────────────────────────
        tone_instruction = CLIENT_PROFILE_TONES.get(
            client_profile, CLIENT_PROFILE_TONES["private_enterprise"]
        )
        await emit(MessageType.THINKING,
                   f"Client profile: '{client_profile}' → tone set. "
                   f"Word budget per section: {max_words}.")

        # ── [HIGH] Pre-compute value-add business impact before any LLM call ──────
        enriched_value_adds = self._enrich_value_adds(pricing)

        # ── [HIGH] Decouple boilerplate — fill templates with string substitution ─
        await emit(MessageType.THINKING,
                   "Filling boilerplate sections (company profile, T&C, support plan) "
                   "via template substitution — no LLM tokens consumed...")

        template_vars = {
            "company_name": company_name,
            "project_name": requirements.project_name,
            "issuing_company": requirements.issuing_company,
            "total": f"{pricing.currency} {pricing.total:,.0f}",
            "currency": pricing.currency,
            "response_deadline": requirements.response_deadline,
        }
        company_profile_text = self._fill_template("company_profile", template_vars)
        support_plan_text    = self._fill_template("support_plan", template_vars)
        tac_text             = self._fill_template("terms_and_conditions", template_vars)

        # ── [CRITICAL] Parallel generation of the 4 creative sections ────────────
        await emit(MessageType.ACTION,
                   "Dispatching 4 creative sections in parallel "
                   "(executive summary, technical proposal, project plan, value proposition)...")

        eval_criteria_str = self._format_list(requirements.evaluation_criteria)
        strategy_summary  = pricing.strategy_summary or "Competitive pricing with value-differentiation."
        win_score         = getattr(pricing, "win_probability_score", "N/A")

        competitor_position_summary = self._build_competitor_summary(pricing)

        # Executive summary task
        exec_task = self._draft_section_with_retry(
            section_name="executive_summary",
            prompt_template=EXEC_SUMMARY_PROMPT,
            prompt_vars={
                "company_name": company_name,
                "max_words": max_words,
                "tone_instruction": tone_instruction,
                "project_name": requirements.project_name,
                "issuing_company": requirements.issuing_company,
                "evaluation_criteria": eval_criteria_str,
                "strategy_summary": strategy_summary,
                "enriched_value_adds": enriched_value_adds,
            },
            additional_instructions=additional_instructions,
        )

        # Technical sections — one task per non-value-add line item
        creative_items = [li for li in pricing.line_items if not getattr(li, "is_value_add", False)]
        tech_tasks = [
            self._draft_section_with_retry(
                section_name="technical_proposal",
                prompt_template=TECHNICAL_SECTION_PROMPT,
                prompt_vars={
                    "company_name": company_name,
                    "max_words": max_words,
                    "tone_instruction": tone_instruction,
                    "item_name": li.item_name,
                    "item_description": li.description or "See specifications.",
                    "quantity": li.quantity,
                    "specifications": getattr(li, "specifications", "As per RFP"),
                    "category": getattr(li, "category", "other"),
                    "is_mandatory": getattr(li, "is_mandatory", True),
                    "priority": getattr(li, "priority", "P1"),
                    "evaluation_criteria": eval_criteria_str,
                },
                additional_instructions=additional_instructions,
            )
            for li in creative_items
        ]

        # Project plan task
        scope_categories = list({
            getattr(li, "category", "other") for li in pricing.line_items
        })
        plan_task = self._draft_section_with_retry(
            section_name="project_plan",
            prompt_template=PROJECT_PLAN_PROMPT,
            prompt_vars={
                "company_name": company_name,
                "max_words": max_words,
                "tone_instruction": tone_instruction,
                "project_timeline": requirements.project_timeline or "As per client requirement.",
                "response_deadline": requirements.response_deadline,
                "scope_item_count": len(requirements.scope_items),
                "scope_categories": ", ".join(scope_categories),
                "evaluation_criteria": eval_criteria_str,
            },
            additional_instructions=additional_instructions,
        )

        # Value proposition task
        vp_task = self._draft_section_with_retry(
            section_name="value_proposition",
            prompt_template=VALUE_PROP_PROMPT,
            prompt_vars={
                "company_name": company_name,
                "max_words": max_words,
                "tone_instruction": tone_instruction,
                "win_probability_score": win_score,
                "strategy_summary": strategy_summary,
                "enriched_value_adds": enriched_value_adds,
                "competitor_position_summary": competitor_position_summary,
            },
            additional_instructions=additional_instructions,
        )

        # Run all creative tasks in parallel
        results = await asyncio.gather(
            exec_task,
            *tech_tasks,
            plan_task,
            vp_task,
            return_exceptions=True,
        )

        exec_summary_text = self._unwrap(results[0], "executive_summary")
        tech_texts        = [self._unwrap(r, f"technical_section_{i}") for i, r in enumerate(results[1:1+len(tech_tasks)])]
        plan_text         = self._unwrap(results[1 + len(tech_tasks)], "project_plan")
        vp_text           = self._unwrap(results[2 + len(tech_tasks)], "value_proposition")

        # ── [HIGH] Compliance matrix — no LLM needed, seeded from Agent 1 ─────────
        compliance_matrix = self._build_compliance_matrix(
            requirements, pricing, creative_items
        )

        await emit(MessageType.RESULT,
            f"Proposal draft complete:\n"
            f"• Executive Summary: ✓\n"
            f"• Technical Sections: {len(tech_texts)} sections\n"
            f"• Project Plan: ✓\n"
            f"• Value Proposition: ✓\n"
            f"• Compliance Matrix: {len(compliance_matrix)} criteria mapped\n"
            f"• Company Profile: ✓ (template)\n"
            f"• Support Plan: ✓ (template)\n"
            f"• Terms & Conditions: ✓ (template)"
        )
        await emit(MessageType.COMPLETE, "Professional proposal draft finalised and ready for review.")

        # Assemble ProposalDraft
        technical_sections = [
            ProposalSection(
                title=creative_items[i].item_name if i < len(creative_items) else f"Section {i+1}",
                content=tech_texts[i],
            )
            for i in range(len(tech_texts))
        ]

        return ProposalDraft(
            executive_summary=exec_summary_text,
            technical_proposal=technical_sections,
            project_plan=plan_text,
            value_proposition=vp_text,
            compliance_matrix=compliance_matrix,
            company_profile=company_profile_text,
            support_plan=support_plan_text,
            terms_and_conditions=tac_text,
        )

    # ------------------------------------------------------------------
    # [CRITICAL] Per-section draft with independent retry
    # ------------------------------------------------------------------
    async def _draft_section_with_retry(
        self,
        section_name: str,
        prompt_template: PromptTemplate,
        prompt_vars: dict,
        additional_instructions: str = "",
    ) -> str:
        """
        Format the section-specific prompt, call the correctly-temperatured LLM,
        and retry up to MAX_SECTION_RETRIES times on failure.
        """
        temperature = SECTION_TEMPERATURES.get(section_name, 0.15)
        llm = self._make_llm(temperature=temperature, max_tokens=1500)

        prompt_text = prompt_template.format(**prompt_vars)
        if additional_instructions:
            prompt_text += f"\n\nADDITIONAL INSTRUCTIONS:\n{additional_instructions}"

        attempt = 0
        last_exc: Exception = RuntimeError("Unknown")
        while attempt < MAX_SECTION_RETRIES:
            attempt += 1
            try:
                msg = await llm.ainvoke(prompt_text)
                content = msg.content if hasattr(msg, "content") else str(msg)
                return content.strip()
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Section '%s' attempt %d/%d failed: %s",
                    section_name, attempt, MAX_SECTION_RETRIES, exc
                )
        raise last_exc

    # ------------------------------------------------------------------
    # [HIGH] Value-add business impact enrichment
    # ------------------------------------------------------------------
    @staticmethod
    def _enrich_value_adds(pricing: PricingStrategy) -> str:
        """
        Pre-compute a business_impact_statement for each value-add before
        any LLM call. Uses delivery_cost and perceived_value_score from Agent 2.
        Format: "Item Name — business_impact_statement (delivery cost: ₹X)"
        """
        if not pricing.value_adds:
            return "No value-adds included in this proposal."

        lines = []
        for va in pricing.value_adds:
            delivery_cost = getattr(va, "value_add_delivery_cost", 0.0) or 0.0
            perceived     = getattr(va, "value_add_perceived_score", 0) or 0

            # Compute a human-readable monetary impact statement
            # Heuristic: estimated client-facing value = delivery_cost * perceived_score factor
            if delivery_cost > 0:
                # e.g. a warranty costing ₹12,000 with perceived score 8 → ₹96,000 risk coverage
                estimated_client_value = delivery_cost * max(perceived, 2)
                impact = (
                    f"eliminates an estimated ₹{estimated_client_value:,.0f} "
                    f"in Year 1 risk/maintenance exposure at no cost to the client"
                )
            elif perceived >= 7:
                impact = "high-perceived-value add-on included at no additional charge"
            else:
                impact = "complimentary service enhancement"

            lines.append(
                f"• {va.item_name}: {impact}. "
                f"(Our delivery cost: ₹{delivery_cost:,.0f})"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # [HIGH] Compliance matrix — seeded from Agent 1's compliance_checklist
    # ------------------------------------------------------------------
    @staticmethod
    def _build_compliance_matrix(
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        line_items: list,
    ) -> list[dict]:
        """
        Produces a list of {criterion, our_response, section_reference, compliant}
        dicts — one per evaluation criterion. Seeds from Agent 1's compliance_checklist,
        then enriches with section references from the line item list.
        No LLM call required.
        """
        checklist: list[dict] = getattr(requirements, "compliance_checklist", []) or []
        eval_criteria: list[str] = requirements.evaluation_criteria or []

        # Build a set of all criteria we need to map
        criteria_map: dict[str, dict] = {}
        for entry in checklist:
            crit = entry.get("criterion", "")
            if crit:
                criteria_map[crit] = {
                    "criterion": crit,
                    "addressable_by_us": entry.get("addressable_by_us", True),
                }
        # Also include any evaluation_criteria not already in checklist
        for crit in eval_criteria:
            if crit not in criteria_map:
                criteria_map[crit] = {
                    "criterion": crit,
                    "addressable_by_us": True,
                }

        # Try to assign a section reference from line items
        item_names = [li.item_name.lower() for li in line_items]

        matrix = []
        for crit, meta in criteria_map.items():
            addressable = meta["addressable_by_us"]
            crit_lower = crit.lower()

            # Simple keyword match to find the most relevant section
            section_ref = "General Proposal"
            for li in line_items:
                if any(kw in crit_lower for kw in li.item_name.lower().split()):
                    section_ref = f"Technical Section — {li.item_name}"
                    break

            matrix.append({
                "criterion": crit,
                "our_response": (
                    "Fully addressed in the technical proposal and project plan."
                    if addressable
                    else "Partially addressed — see additional notes. Human review recommended."
                ),
                "section_reference": section_ref,
                "compliant": addressable,
            })

        return matrix

    # ------------------------------------------------------------------
    # [HIGH] Template substitution — zero LLM tokens for boilerplate
    # ------------------------------------------------------------------
    @staticmethod
    def _fill_template(template_name: str, vars: dict) -> str:
        """
        Calls the existing template_filler_tool for initial content,
        then performs variable substitution for known placeholders.
        No LLM involved.
        """
        try:
            raw = template_filler_tool.invoke(
                {"template_name": template_name, "structured_data": json.dumps(vars)}
            )
        except Exception as exc:
            logger.warning("template_filler_tool failed for '%s': %s", template_name, exc)
            raw = f"[Template '{template_name}' unavailable — please fill manually.]"

        # Replace known placeholders with actual values
        for key, val in vars.items():
            raw = raw.replace(f"{{{{{key}}}}}", str(val)).replace(f"[{key}]", str(val))
        return raw

    # ------------------------------------------------------------------
    # [MEDIUM] Word budget from RFP submission requirements
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_word_budget(submission_requirements: list[str]) -> int:
        """
        Scans submission_requirements for page/word count constraints.
        e.g. "maximum 20 pages" → 300 words/page * 20 = 6000 → 6000/7 sections ≈ 857/section
        Falls back to DEFAULT_MAX_WORDS if none found.
        """
        page_pattern = re.compile(r"(\d+)\s*(?:page|pages|pg)", re.IGNORECASE)
        word_pattern = re.compile(r"(\d+)\s*(?:word|words)", re.IGNORECASE)

        for req in (submission_requirements or []):
            wm = word_pattern.search(req)
            if wm:
                total_words = int(wm.group(1))
                return max(150, total_words // 7)   # 7 sections
            pm = page_pattern.search(req)
            if pm:
                total_pages = int(pm.group(1))
                total_words = total_pages * 300     # ~300 words/page
                return max(150, total_words // 7)

        return DEFAULT_MAX_WORDS

    # ------------------------------------------------------------------
    # [MEDIUM] Competitor position summary for value proposition prompt
    # ------------------------------------------------------------------
    @staticmethod
    def _build_competitor_summary(pricing: PricingStrategy) -> str:
        if not pricing.competitor_analyses:
            return "No direct competitor pricing data available for this proposal."
        lines = []
        for ca in pricing.competitor_analyses[:5]:   # cap at 5 to control prompt size
            gap = getattr(ca, "price_difference_pct", 0)
            strategy = "MATCH" if getattr(ca, "can_match", True) else "PIVOT"
            lines.append(
                f"• {ca.product_id}: our price is {gap:+.1f}% vs {ca.competitor_name} "
                f"(strategy: {strategy})"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_list(items: list[str]) -> str:
        if not items:
            return "No specific evaluation criteria stated in the RFP."
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _unwrap(result, section_name: str) -> str:
        """Unwrap asyncio.gather result — return text or a safe fallback string."""
        if isinstance(result, Exception):
            logger.error("Section '%s' failed after retries: %s", section_name, result)
            return (
                f"[Section '{section_name}' could not be generated automatically. "
                f"Please draft manually before sending. Error: {result}]"
            )
        return str(result)

    # ------------------------------------------------------------------
    # Fallback — kept from v1, now only triggers on total draft failure
    # ------------------------------------------------------------------
    def _generate_fallback(
        self,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        company_name: str,
        error: str = "",
    ) -> ProposalDraft:
        """Emergency fallback when the parallel gather itself raises."""
        items_list = "\n".join(
            f"- {item.item_name} (Qty: {item.quantity})" for item in pricing.line_items
        )
        value_adds_list = "\n".join(
            f"- {va.item_name}: {va.description}" for va in pricing.value_adds
        ) if pricing.value_adds else "No additional value-adds."

        return ProposalDraft(
            executive_summary=(
                f"{company_name} is pleased to present this proposal for "
                f"{requirements.project_name} as requested by {requirements.issuing_company}. "
                f"Our team brings extensive expertise in enterprise IT infrastructure solutions."
            ),
            technical_proposal=[
                ProposalSection(
                    title=item.item_name,
                    content=f"We propose {item.quantity} unit(s) of {item.item_name}. {item.description}",
                )
                for item in pricing.line_items
                if not getattr(item, "is_value_add", False)
            ],
            project_plan=f"Project plan aligned with: {requirements.project_timeline}",
            value_proposition=(
                f"Beyond pricing, {company_name} differentiates through:\n{value_adds_list}"
            ),
            compliance_matrix=[],
            company_profile=(
                f"{company_name} has extensive experience delivering enterprise IT infrastructure. "
                f"We maintain certifications with leading technology vendors."
            ),
            support_plan=(
                "24/7 priority technical support | 4-hour critical response | "
                "Proactive monitoring | Quarterly health checks."
            ),
            terms_and_conditions=(
                "Payment: 50% advance, 50% on completion. "
                "Warranty: Manufacturer terms + extended coverage. "
                "All prices exclusive of applicable taxes."
            ),
        )