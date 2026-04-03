"""
Junior Analyst Agent
====================
Responsible for parsing unstructured RFP documents and extracting
key requirements into a structured format.
"""

import json
from typing import Callable, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from app.models import (
    ExtractedRequirements, ScopeItem, AgentMessage,
    AgentRole, MessageType
)
from app.config import settings


EXTRACTION_PROMPT = PromptTemplate.from_template("""You are a "Junior Analyst" — an expert RFP document analyst working for an SME. 
Your job is to carefully parse the following Request for Proposal (RFP) document and extract ALL key information into a structured JSON format.

Be thorough and precise. Extract every detail that would be needed to prepare a competitive quotation.

RFP DOCUMENT:
---
{rfp_text}
---

Extract the following information and return ONLY a valid JSON object (no markdown, no explanation):

{{
  "project_name": "name/title of the project",
  "issuing_company": "company that issued the RFP",
  "date_issued": "date the RFP was issued",
  "response_deadline": "deadline for responses",
  "scope_items": [
    {{
      "item_name": "name of the item/service",
      "description": "detailed description",
      "quantity": number,
      "specifications": "any specific specs or requirements",
      "category": "hardware OR software OR service"
    }}
  ],
  "budget_amount": number (0 if not specified),
  "budget_currency": "currency code like INR, USD",
  "evaluation_criteria": ["criterion 1", "criterion 2"],
  "project_timeline": "overall timeline description",
  "submission_requirements": ["requirement 1", "requirement 2"],
  "additional_notes": "any other important information"
}}

IMPORTANT:
- Extract ALL scope items, including hardware, software, and services
- If quantities are mentioned, include them
- Parse budget amounts as numbers (e.g., 5000000 for ₹50,00,000)
- If information is not found, use empty string or 0
- IF the document does not appear to be a valid RFP (e.g. just a greeting, a single word, or nonsense), return ONLY: {{"error": "Invalid RFP document"}}
- Return ONLY the JSON object, nothing else""")


class JuniorAnalyst:
    """Parses unstructured RFP text and extracts structured requirements."""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.1,
            max_tokens=4096,
        )
        self.role = AgentRole.JUNIOR_ANALYST

    async def analyze(
        self,
        rfp_text: str,
        emit_message: Optional[Callable] = None,
        additional_instructions: str = ""
    ) -> ExtractedRequirements:
        """Parse RFP text and extract structured requirements."""

        async def emit(msg_type: MessageType, content: str):
            if emit_message:
                await emit_message(AgentMessage(
                    agent=self.role,
                    message_type=msg_type,
                    content=content
                ))

        await emit(MessageType.STATUS, "Starting RFP document analysis...")
        await emit(MessageType.THINKING, "Scanning the RFP document to identify key sections: scope of work, budget, timeline, and evaluation criteria...")

        # Build prompt
        prompt_text = EXTRACTION_PROMPT.format(rfp_text=rfp_text)

        if additional_instructions:
            prompt_text += f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{additional_instructions}"

        await emit(MessageType.ACTION, "Parsing RFP document to extract structured requirements using AI analysis...")

        # Call LLM
        try:
            response_msg = await self.llm.ainvoke(prompt_text)
            response = str(response_msg.content) if hasattr(response_msg, 'content') else str(response_msg)
        except Exception as e:
            await emit(MessageType.ERROR, f"Error communicating with LLM: {str(e)}")
            raise

        await emit(MessageType.THINKING, "Processing AI response and validating extracted data...")

        # Parse JSON response
        requirements = self._parse_response(response)

        # Emit results summary
        await emit(MessageType.RESULT,
            f"Successfully extracted requirements:\n"
            f"• Project: {requirements.project_name}\n"
            f"• Client: {requirements.issuing_company}\n"
            f"• Scope Items: {len(requirements.scope_items)} items identified\n"
            f"• Budget: {requirements.budget_currency} {requirements.budget_amount:,.0f}\n"
            f"• Deadline: {requirements.response_deadline}"
        )

        for item in requirements.scope_items:
            await emit(MessageType.ACTION,
                f"Identified → {item.item_name} (Qty: {item.quantity}, Category: {item.category})"
            )

        await emit(MessageType.COMPLETE, "RFP analysis complete. All requirements extracted and structured.")

        return requirements

    def _parse_response(self, response: str) -> ExtractedRequirements:
        """Parse the LLM response into ExtractedRequirements."""
        try:
            # Try to extract JSON from response
            text = response.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            # Find JSON object boundaries
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

            data = json.loads(text)

            if "error" in data:
                raise ValueError("The provided document does not appear to be a valid Request for Proposal (RFP). Please provide a detailed RFP.")

            # Build scope items
            scope_items = []
            for item_data in data.get("scope_items", []):
                scope_items.append(ScopeItem(
                    item_name=item_data.get("item_name", ""),
                    description=item_data.get("description", ""),
                    quantity=int(item_data.get("quantity", 1)),
                    specifications=item_data.get("specifications", ""),
                    category=item_data.get("category", ""),
                ))

            return ExtractedRequirements(
                project_name=data.get("project_name", ""),
                issuing_company=data.get("issuing_company", ""),
                date_issued=data.get("date_issued", ""),
                response_deadline=data.get("response_deadline", ""),
                scope_items=scope_items,
                budget_amount=float(data.get("budget_amount", 0)),
                budget_currency=data.get("budget_currency", "INR"),
                evaluation_criteria=data.get("evaluation_criteria", []),
                project_timeline=data.get("project_timeline", ""),
                submission_requirements=data.get("submission_requirements", []),
                additional_notes=data.get("additional_notes", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Fallback: return empty requirements
            return ExtractedRequirements(
                additional_notes=f"Failed to parse LLM response: {str(e)}. Raw: {response[:500]}"
            )
