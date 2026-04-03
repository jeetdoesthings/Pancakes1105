"""
Senior Copywriter Agent
=======================
Drafts professional, persuasive proposal content based on
extracted requirements and pricing strategy.
"""

import json
from typing import Callable, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from app.models import (
    ExtractedRequirements, PricingStrategy, ProposalDraft, ProposalSection,
    AgentMessage, AgentRole, MessageType
)
from app.config import settings


PROPOSAL_PROMPT = PromptTemplate.from_template("""You are a "Senior Copywriter" — an expert proposal writer for an SME called "{company_name}".

Your job is to draft a professional, persuasive, and boardroom-ready proposal based on the following data.

CLIENT RFP REQUIREMENTS:
{requirements_json}

PRICING STRATEGY & LINE ITEMS:
{pricing_json}

COMPANY NAME: {company_name}

Write professional proposal content for each section below. The tone should be confident, professional, and client-focused. Emphasize reliability, expertise, and the value-adds that differentiate us from competitors.

Return ONLY a valid JSON object with these sections:

{{
  "executive_summary": "A compelling 2-3 paragraph executive summary highlighting our expertise, understanding of the client's needs, and why we are the best choice. Mention specific products and our value-differentiation strategy without explicitly naming competitors.",
  
  "technical_sections": [
    {{
      "title": "section title (e.g., 'Server Hardware')",
      "content": "detailed technical description of what we're proposing for this item"
    }}
  ],
  
  "project_plan": "Detailed project plan and timeline broken into phases, based on the RFP requirements.",
  
  "value_proposition": "A strong paragraph explaining our unique value proposition, including any value-adds we're offering (e.g., extended warranty, premium support) and WHY they benefit the client. This is where you highlight what makes our proposal superior.",
  
  "company_profile": "A professional company profile for {company_name} emphasizing experience in IT infrastructure, number of years in business, certifications, and key differentiators.",
  
  "support_plan": "Detailed support and maintenance plan including response times, monitoring, health checks, and escalation procedures.",
  
  "terms_and_conditions": "Standard professional terms and conditions including payment terms, warranty, delivery, and liability."
}}

IMPORTANT:
- Be specific and reference actual products/items from the pricing data
- Mention value-adds naturally as part of the proposal, not as a defensive move
- Keep each section professional and concise
- Return ONLY the JSON object, no other text""")


class SeniorCopywriter:
    """Drafts professional proposal content using LLM."""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_NAME,
            temperature=0.4,
            max_tokens=6000,
        )
        self.role = AgentRole.SENIOR_COPYWRITER

    async def draft(
        self,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        company_name: str = "Ering Solutions",
        emit_message: Optional[Callable] = None,
        additional_instructions: str = ""
    ) -> ProposalDraft:
        """Draft professional proposal content."""

        async def emit(msg_type: MessageType, content: str):
            if emit_message:
                await emit_message(AgentMessage(
                    agent=self.role,
                    message_type=msg_type,
                    content=content
                ))

        await emit(MessageType.STATUS, "Starting professional proposal drafting...")
        await emit(MessageType.THINKING,
            f"Preparing to draft proposal for {requirements.issuing_company}'s "
            f"'{requirements.project_name}' project. Incorporating pricing strategy "
            f"and {len(pricing.value_adds)} value-add recommendations..."
        )

        # Build prompt
        requirements_json = json.dumps(requirements.model_dump(), indent=2, default=str)
        pricing_json = json.dumps(pricing.model_dump(), indent=2, default=str)

        prompt_text = PROPOSAL_PROMPT.format(
            requirements_json=requirements_json,
            pricing_json=pricing_json,
            company_name=company_name,
        )

        if additional_instructions:
            prompt_text += f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{additional_instructions}"

        await emit(MessageType.ACTION, "Drafting Executive Summary and introduction...")
        await emit(MessageType.ACTION, "Composing Technical Proposal sections for each deliverable...")
        await emit(MessageType.ACTION, "Writing Value Proposition with competitive differentiation...")

        # Call LLM
        try:
            response_msg = await self.llm.ainvoke(prompt_text)
            response = str(response_msg.content) if hasattr(response_msg, 'content') else str(response_msg)
        except Exception as e:
            await emit(MessageType.ERROR, f"Error generating proposal draft: {str(e)}")
            raise

        await emit(MessageType.THINKING, "Processing and structuring the draft content...")

        # Parse response
        draft = self._parse_response(response, requirements, pricing, company_name)

        await emit(MessageType.RESULT,
            f"Proposal draft complete:\n"
            f"• Executive Summary: ✓\n"
            f"• Technical Sections: {len(draft.technical_proposal)} sections\n"
            f"• Project Plan: ✓\n"
            f"• Value Proposition: ✓\n"
            f"• Company Profile: ✓\n"
            f"• Support Plan: ✓\n"
            f"• Terms & Conditions: ✓"
        )

        await emit(MessageType.COMPLETE, "Professional proposal draft finalized and ready for review.")

        return draft

    def _parse_response(
        self, response: str,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        company_name: str
    ) -> ProposalDraft:
        """Parse LLM response into ProposalDraft."""
        try:
            text = response.strip()

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

            data = json.loads(text)

            technical_sections = []
            for section in data.get("technical_sections", []):
                technical_sections.append(ProposalSection(
                    title=section.get("title", ""),
                    content=section.get("content", "")
                ))

            return ProposalDraft(
                executive_summary=data.get("executive_summary", ""),
                technical_proposal=technical_sections,
                project_plan=data.get("project_plan", ""),
                value_proposition=data.get("value_proposition", ""),
                company_profile=data.get("company_profile", ""),
                support_plan=data.get("support_plan", ""),
                terms_and_conditions=data.get("terms_and_conditions", ""),
            )
        except Exception as e:
            # Fallback: generate basic content
            return self._generate_fallback(requirements, pricing, company_name, str(e))

    def _generate_fallback(
        self,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        company_name: str,
        error: str = ""
    ) -> ProposalDraft:
        """Generate fallback proposal content when LLM parsing fails."""

        items_list = "\n".join(
            f"- {item.item_name} (Qty: {item.quantity})" for item in pricing.line_items
        )
        value_adds_list = "\n".join(
            f"- {va.item_name}: {va.description}" for va in pricing.value_adds
        ) if pricing.value_adds else "No additional value-adds."

        executive_summary = (
            f"{company_name} is pleased to present this comprehensive proposal for the "
            f"{requirements.project_name} project as requested by {requirements.issuing_company}. "
            f"Our team brings extensive expertise in delivering enterprise-grade IT infrastructure "
            f"solutions, and we are confident in our ability to meet and exceed your requirements. "
            f"This proposal outlines our technical approach, competitive pricing, and the additional "
            f"value we bring through our premium support and strategic value-adds."
        )

        technical_sections = []
        for item in pricing.line_items:
            if not item.is_value_add:
                technical_sections.append(ProposalSection(
                    title=item.item_name,
                    content=f"We propose {item.quantity} unit(s) of {item.item_name}. {item.description}"
                ))

        return ProposalDraft(
            executive_summary=executive_summary,
            technical_proposal=technical_sections,
            project_plan=f"Our project plan aligns with the requested timeline: {requirements.project_timeline}",
            value_proposition=(
                f"Beyond competitive pricing, {company_name} differentiates through strategic "
                f"value-adds included at no additional cost:\n{value_adds_list}"
            ),
            company_profile=(
                f"{company_name} has over 10 years of experience delivering robust IT infrastructure "
                f"solutions across India. We are certified partners with Dell, Cisco, and VMware."
            ),
            support_plan=(
                "Our Premium Support Package includes: 24/7 priority technical support, "
                "proactive monitoring and alerts, quarterly health checks, and guaranteed "
                "4-hour response time for critical issues."
            ),
            terms_and_conditions=(
                "Payment Terms: 50% advance, 50% on completion. "
                "Warranty: As per manufacturer terms plus our extended coverage. "
                "Delivery: As per project timeline. "
                "All prices are exclusive of applicable taxes unless stated otherwise."
            ),
        )
