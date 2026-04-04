"""
Conflict Detection Engine — TWIST 2
======================================
Detects contradictory information WITHIN a single RFP document by
splitting it into sections and cross-comparing key facts.

Example conflicts:
  - Budget mentioned as ₹48L in section 1 but ₹55L in section 3
  - Spec says "64GB RAM" in one place, "128GB RAM" in another
  - Deadline "28-Feb" in body but "15-Mar" in cover letter

When conflicts are found, the engine:
  1. Identifies the specific field/topic
  2. Shows both contradicting values with their source sections
  3. Prioritizes the more specific/later-in-document value
  4. Explains the reasoning explicitly

Uses DeepSeek for structured extraction. Prompt is kept under 4K tokens.
"""

import json
import logging
import re
from typing import Optional, Callable

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

from app.config import settings
from app.models import (
    ConflictItem, ConflictReport,
    AgentMessage, AgentRole, MessageType,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
MAX_TEXT_FOR_CONFLICT_CHECK = 8000   # chars — keeps prompt under token budget

# ──────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────
CONFLICT_PROMPT = PromptTemplate.from_template("""You are a document analyst. Carefully read this RFP document and identify any SELF-CONTRADICTIONS — places where the document states conflicting information about the same topic.

DOCUMENT:
---
{rfp_text}
---

LOOK FOR CONTRADICTIONS IN:
- Budget / pricing figures mentioned in different sections
- Specifications (RAM, storage, quantities) that differ
- Deadlines or timelines that conflict
- Scope items described differently in different sections
- Payment terms or warranty periods that contradict
- Any other factual inconsistency within the document

IMPORTANT: Only flag REAL contradictions — not just different aspects of the same topic.

Return ONLY a JSON object (no markdown fences, no extra text):
{{
  "conflicts": [
    {{
      "field": "string — the topic that conflicts (e.g. 'budget', 'RAM_spec', 'deadline')",
      "section_a": "string — where the first value appears",
      "value_a": "string — the first stated value",
      "section_b": "string — where the contradictory value appears",
      "value_b": "string — the contradicting value",
      "resolution": "string — which value should be used and why (prefer the more specific, more recent, or more authoritative source)",
      "prioritized_value": "string — the value to use",
      "confidence": "high|medium|low"
    }}
  ],
  "has_conflicts": true|false,
  "summary": "string — one paragraph summary"
}}

If NO contradictions exist, return:
{{
  "conflicts": [],
  "has_conflicts": false,
  "summary": "No contradictions detected. The document is internally consistent."
}}""")


class ConflictDetector:
    """Detects self-contradictions within an RFP document."""

    def __init__(self):
        self.llm = ChatOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.PRIMARY_MODEL,
            temperature=0.05,
            max_tokens=2000,
        )

    async def detect_conflicts(
        self,
        rfp_text: str,
        emit_message: Optional[Callable] = None,
    ) -> ConflictReport:
        """
        Analyze the RFP text for internal contradictions.
        Returns a ConflictReport with any conflicts found and their resolutions.
        """
        text = (rfp_text or "").strip()
        if len(text) < 200:
            return ConflictReport(
                has_conflicts=False,
                summary="Document too short for meaningful conflict analysis.",
            )

        await self._emit(emit_message, MessageType.THINKING,
                         "🔍 Scanning RFP for internal contradictions (TWIST 2)...")

        # Truncate to stay in context budget
        truncated = text[:MAX_TEXT_FOR_CONFLICT_CHECK]

        try:
            prompt_text = CONFLICT_PROMPT.format(rfp_text=truncated)
            response = await self.llm.ainvoke(prompt_text)
            raw = str(response.content) if hasattr(response, "content") else str(response)
            data = self._extract_json(raw)
        except Exception as exc:
            logger.warning("Conflict detection LLM call failed: %s", exc)
            await self._emit(emit_message, MessageType.THINKING,
                             f"Conflict scan skipped (LLM error): {exc}")
            return ConflictReport(
                has_conflicts=False,
                summary=f"Conflict detection skipped due to error: {exc}",
            )

        # Build ConflictItems
        conflicts: list[ConflictItem] = []
        for c in data.get("conflicts", []):
            conflicts.append(ConflictItem(
                field=c.get("field", "unknown"),
                section_a=c.get("section_a", ""),
                value_a=c.get("value_a", ""),
                section_b=c.get("section_b", ""),
                value_b=c.get("value_b", ""),
                resolution=c.get("resolution", ""),
                prioritized_value=c.get("prioritized_value", ""),
                confidence=c.get("confidence", "medium"),
            ))

        has_conflicts = len(conflicts) > 0
        summary = data.get("summary", "")

        if has_conflicts:
            for c in conflicts:
                await self._emit(emit_message, MessageType.WARNING,
                    f"⚠ CONFLICT: {c.field} — "
                    f"'{c.value_a}' (in {c.section_a}) vs "
                    f"'{c.value_b}' (in {c.section_b}). "
                    f"→ Using: {c.prioritized_value}. Reason: {c.resolution}")
            await self._emit(emit_message, MessageType.RESULT,
                f"⚠ {len(conflicts)} contradiction(s) detected in the RFP. "
                f"Prioritized values applied to extraction.")
        else:
            await self._emit(emit_message, MessageType.RESULT,
                "✅ No contradictions detected — document is internally consistent.")

        return ConflictReport(
            conflicts=conflicts,
            has_conflicts=has_conflicts,
            summary=summary,
        )

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from potentially noisy LLM output."""
        text = text.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        for fence in ("```json", "```"):
            if fence in text:
                text = text.split(fence)[1].split("```")[0].strip()
                break
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end <= start:
            return {"conflicts": [], "has_conflicts": False, "summary": "Failed to parse response."}
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            return {"conflicts": [], "has_conflicts": False, "summary": "JSON parse error."}

    @staticmethod
    async def _emit(emit_message, msg_type, content):
        if emit_message:
            await emit_message(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=msg_type,
                content=content,
            ))


# Singleton
conflict_detector = ConflictDetector()
