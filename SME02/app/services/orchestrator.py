"""
Multi-Agent Orchestrator (LangGraph Edition)
============================================
Coordinates the three AI agents sequentially using LangGraph for robust 
state machines, human-in-the-loop breakpoints, and conditional routing.
"""

import uuid
import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_core.runnables import RunnableConfig

from app.models import (
    RFPInput, JobState, JobStatus, AgentMessage, AgentRole,
    MessageType, HumanFeedback, GraphState, SupportTicket, ConflictReport
)
from app.agents.junior_analyst import JuniorAnalyst
from app.agents.pricing_strategist import PricingStrategist
from app.agents.senior_copywriter import SeniorCopywriter
from app.services.pdf_generator import PDFGenerator
from app.services.rag_service import rag_service
from app.compliance_engine import validate_proposal_compliance


async def _noop_emit(_msg: AgentMessage) -> None:
    """Used when no SSE client is attached (e.g. tests)."""
    return


class Orchestrator:
    """Manages the LangGraph multi-agent workflow for RFP processing."""

    def __init__(self):
        self.junior_analyst = JuniorAnalyst()
        self.pricing_strategist = PricingStrategist()
        self.senior_copywriter = SeniorCopywriter()
        self.pdf_generator = PDFGenerator()
        
        # We store streaming logs locally in memory to avoid crushing the checkpointer
        # with high-frequency state updates.
        self.job_messages: dict[str, list[AgentMessage]] = {}
        # Revision feedback submitted via POST (large payloads); consumed by GET SSE.
        self._pending_feedback: dict[str, HumanFeedback] = {}

        self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(GraphState)

        # 1. Add Nodes
        workflow.add_node("junior_analyst", self._node_junior_analyst)
        workflow.add_node("pricing_strategist", self._node_pricing_strategist)
        workflow.add_node("senior_copywriter", self._node_senior_copywriter)
        workflow.add_node("ticket_generator", self._node_ticket_generator)
        workflow.add_node("approve_gate", self._node_approve_gate)
        workflow.add_node("pdf_generator", self._node_pdf_generator)

        # 2. Add Linear Edges
        workflow.add_edge(START, "junior_analyst")
        workflow.add_edge("junior_analyst", "pricing_strategist")
        workflow.add_edge("pricing_strategist", "senior_copywriter")
        workflow.add_edge("senior_copywriter", "ticket_generator")
        workflow.add_edge("ticket_generator", "approve_gate")

        # 3. Add Conditional Routing from HITL Breakpoint
        workflow.add_conditional_edges(
            "approve_gate",
            self._route_feedback,
            {
                "junior_analyst": "junior_analyst",
                "pricing_strategist": "pricing_strategist",
                "senior_copywriter": "senior_copywriter",
                "pdf_generator": "pdf_generator"
            }
        )
        workflow.add_edge("pdf_generator", END)

        # 4. Compile with native interruption before the approval gate
        self.memory = MemorySaver()
        self.graph = workflow.compile(
            checkpointer=self.memory,
            interrupt_before=["approve_gate"]  # Pauses right before gating/routing
        )

    def create_job(self, rfp_input: RFPInput) -> str:
        """Initialize the job and local state tracker."""
        job_id = str(uuid.uuid4())[:8]
        self.job_messages[job_id] = []
        
        config = {"configurable": {"thread_id": job_id}}
        initial_state = GraphState(
            job_id=job_id,
            status=JobStatus.PENDING,
            rfp_input=rfp_input,
            revision_count=0
        )
        self.graph.update_state(config, initial_state)
        
        # Populate the Vector Store with the RFP Document chunks
        rag_service.process_and_store(job_id, rfp_input.rfp_text)
        
        return job_id

    def set_pending_feedback(self, job_id: str, feedback: HumanFeedback) -> None:
        """Store feedback from POST /api/revise before the client opens the SSE GET stream."""
        self._pending_feedback[job_id] = feedback

    def pop_pending_feedback(self, job_id: str) -> Optional[HumanFeedback]:
        """Retrieve and remove feedback queued for the revise SSE stream."""
        return self._pending_feedback.pop(job_id, None)

    def get_job(self, job_id: str) -> Optional[JobState]:
        """Fetch the state from LangGraph checkpointer and bundle messages."""
        config = {"configurable": {"thread_id": job_id}}
        try:
            state_values = self.graph.get_state(config).values
            if not state_values:
                return None
            
            # Map into our standard JobState for the API responses
            return JobState(
                job_id=state_values.get("job_id"),
                status=state_values.get("status", JobStatus.PENDING),
                rfp_input=state_values.get("rfp_input"),
                extracted_requirements=state_values.get("extracted_requirements"),
                pricing_strategy=state_values.get("pricing_strategy"),
                proposal_draft=state_values.get("proposal_draft"),
                support_ticket=state_values.get("support_ticket"),
                pdf_path=state_values.get("pdf_path"),
                messages=self.job_messages.get(job_id, []),
                revision_count=state_values.get("revision_count", 0)
            )
        except Exception as e:
            logger.warning("get_job failed for %s: %s", job_id, e, exc_info=True)
            return None

    def _wrap_emitter(self, job_id: str, client_emit: Optional[Callable]) -> Callable:
        """Wraps the client SSE emitter to securely buffer logs to local memory."""
        async def stateful_emit(msg: AgentMessage):
            msg.timestamp = datetime.now().isoformat()
            if job_id not in self.job_messages:
                self.job_messages[job_id] = []
            self.job_messages[job_id].append(msg)
            if client_emit:
                await client_emit(msg)
        return stateful_emit

    async def process_rfp(self, job_id: str, emit_message: Optional[Callable] = None) -> JobState:
        """Trigger initial execution of the LangGraph state machine."""
        wrapped_emit = self._wrap_emitter(job_id, emit_message)
        config = {"configurable": {"thread_id": job_id, "emit": wrapped_emit}}
        
        try:
            await self.graph.ainvoke(None, config)
        except Exception as e:
            # Catch overarching execution failures
            await wrapped_emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ERROR,
                content=f"Error executing AI Workflow: {str(e)}"
            ))
            self.graph.update_state(config, {"status": JobStatus.ERROR})
        
        return self.get_job(job_id)

    async def handle_feedback(self, job_id: str, feedback: HumanFeedback, emit_message: Optional[Callable] = None) -> JobState:
        """Updates graph state with feedback and resumes execution path seamlessly."""
        wrapped_emit = self._wrap_emitter(job_id, emit_message)
        config = {"configurable": {"thread_id": job_id, "emit": wrapped_emit}}
        
        # Process revisions internally before resuming
        state = self.graph.get_state(config).values
        rev_count = state.get("revision_count", 0)
        
        if not feedback.approved:
            rev_count += 1
            await wrapped_emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.STATUS,
                content=f"📝 Processing your changes (Revision #{rev_count})..."
            ))
            self.graph.update_state(config, {"feedback": feedback, "revision_count": rev_count, "status": JobStatus.REVISING})
        else:
            self.graph.update_state(config, {"feedback": feedback})

        # Resume execution (will pop the interrupt_before gate)
        await self.graph.ainvoke(None, config)
        return self.get_job(job_id)

    async def approve_and_generate(self, job_id: str, emit_message: Optional[Callable] = None) -> JobState:
        """Convenience method unifying the hit-back into a direct approval."""
        feedback = HumanFeedback(approved=True, changes=[])
        return await self.handle_feedback(job_id, feedback, emit_message)


    # --- LangGraph Nodes ---

    async def _node_junior_analyst(self, state: GraphState, config: RunnableConfig):
        emit = config["configurable"].get("emit") or _noop_emit
        
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.STATUS,
            content="🚀 Initiating RFP processing pipeline..."
        ))
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.ACTION,
            content="Activating Junior Analyst agent for RFP document parsing..."
        ))

        instructions = ""
        feedback = state.get("feedback")
        if feedback and not feedback.approved:
            changes = [c.instruction for c in feedback.changes if c.target_agent == AgentRole.JUNIOR_ANALYST]
            if changes:
                instructions = "\n".join(changes)
                await emit(AgentMessage(
                    agent=AgentRole.ORCHESTRATOR,
                    message_type=MessageType.ACTION,
                    content=f"Re-running Junior Analyst with changes: {instructions}"
                ))

        requirements, _ = await self.junior_analyst.analyze(
            job_id=state["job_id"],
            rfp_text=state["rfp_input"].rfp_text,
            emit_message=emit,
            additional_instructions=instructions
        )
        return {"extracted_requirements": requirements, "status": JobStatus.ANALYZING}

    async def _node_pricing_strategist(self, state: GraphState, config: RunnableConfig):
        emit = config["configurable"].get("emit") or _noop_emit
        
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.ACTION,
            content="Activating Pricing Strategist agent for competitive analysis & dynamic market research..."
        ))

        instructions = ""
        feedback = state.get("feedback")
        if feedback and not feedback.approved:
            changes = [c.instruction for c in feedback.changes if c.target_agent == AgentRole.PRICING_STRATEGIST]
            if any(t == AgentRole.JUNIOR_ANALYST for t in [c.target_agent for c in feedback.changes]):
                instructions += "Note: Requirements were updated by the Junior Analyst. Please re-analyze based on new data.\n"
            instructions += "\n".join(changes)
            
            if instructions.strip():
                await emit(AgentMessage(
                    agent=AgentRole.ORCHESTRATOR,
                    message_type=MessageType.ACTION,
                    content="Re-running Pricing Strategist with your changes..."
                ))

        strategy = await self.pricing_strategist.analyze(
            requirements=state["extracted_requirements"],
            emit_message=emit,
            additional_instructions=instructions
        )
        return {"pricing_strategy": strategy, "status": JobStatus.PRICING}

    async def _node_senior_copywriter(self, state: GraphState, config: RunnableConfig):
        emit = config["configurable"].get("emit") or _noop_emit
        
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.ACTION,
            content="Activating Senior Copywriter agent for proposal drafting..."
        ))

        instructions = ""
        feedback = state.get("feedback")
        if feedback and not feedback.approved:
            changes = [c.instruction for c in feedback.changes if c.target_agent == AgentRole.SENIOR_COPYWRITER]
            if any(t in [AgentRole.JUNIOR_ANALYST, AgentRole.PRICING_STRATEGIST] for t in [c.target_agent for c in feedback.changes]):
                instructions += "Note: Pricing strategy or requirements were updated. Please incorporate the changes natively into the copy.\n"
            instructions += "\n".join(changes)
            
            if instructions.strip():
                await emit(AgentMessage(
                    agent=AgentRole.ORCHESTRATOR,
                    message_type=MessageType.ACTION,
                    content="Re-running Senior Copywriter with your changes..."
                ))

        draft = await self.senior_copywriter.draft(
            requirements=state["extracted_requirements"],
            pricing=state["pricing_strategy"],
            company_name=state["rfp_input"].company_name,
            emit_message=emit,
            additional_instructions=instructions
        )

        if state.get("revision_count", 0) > 0:
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.STATUS,
                content="✅ Revisions complete. Updated proposal is ready for your review."
            ))
        else:
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.STATUS,
                content="✅ All agents have completed their work. Proposal is ready for your review and approval."
            ))

        return {"proposal_draft": draft, "status": JobStatus.AWAITING_APPROVAL}

    async def _node_ticket_generator(self, state: GraphState, config: RunnableConfig):
        """TWIST 1: Auto-generate a CRM support ticket from the pipeline output."""
        emit = config["configurable"].get("emit") or _noop_emit

        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.ACTION,
            content="🎫 Auto-generating CRM support ticket from analysis (TWIST 1)..."
        ))

        try:
            ticket = await self._generate_support_ticket(state, emit)

            ticket_summary = (
                f"✅ CRM Support Ticket Auto-Filled:\n"
                f"• Ticket: {ticket.ticket_id}\n"
                f"• Client: {ticket.client_company}\n"
                f"• Issue: {ticket.issue_summary}\n"
                f"• Category: {ticket.issue_category}\n"
                f"• Confidence: {ticket.confidence}"
            )
            if ticket.conflict_report and ticket.conflict_report.has_conflicts:
                ticket_summary += f"\n• ⚠ Conflicts: {len(ticket.conflict_report.conflicts)} detected & auto-resolved"

            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.RESULT,
                content=ticket_summary
            ))

            return {"support_ticket": ticket}
        except Exception as e:
            logger.warning("Ticket auto-generation failed: %s", e)
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.THINKING,
                content=f"CRM ticket auto-fill skipped: {e}"
            ))
            return {}

    async def _generate_support_ticket(self, state: GraphState, emit) -> SupportTicket:
        """Build a support ticket deterministically from pipeline state."""
        import uuid as _uuid
        from langchain_openai import ChatOpenAI
        import json
        import re

        requirements = state.get("extracted_requirements")
        pricing = state.get("pricing_strategy")
        proposal = state.get("proposal_draft")
        rfp_input = state.get("rfp_input")

        # Build context summary from extracted data
        context_parts = []
        if requirements:
            context_parts.append(f"Project: {requirements.project_name}")
            context_parts.append(f"Client: {requirements.issuing_company}")
            context_parts.append(f"Budget: {requirements.budget_currency} {requirements.budget_amount:,.0f}")
            context_parts.append(f"Deadline: {requirements.response_deadline}")
            context_parts.append(f"Scope items: {len(requirements.scope_items)}")
            if requirements.disqualification_criteria:
                context_parts.append(f"Disqualification risks: {'; '.join(requirements.disqualification_criteria)}")
        if pricing:
            context_parts.append(f"Quoted total: {pricing.currency} {pricing.total:,.0f}")
            context_parts.append(f"Strategy: {pricing.strategy_summary[:200]}" if pricing.strategy_summary else "")

        context_text = "\n".join([c for c in context_parts if c])

        # Use DeepSeek to generate ticket fields
        from app.config import settings as _settings
        llm = ChatOpenAI(
            base_url=_settings.DEEPSEEK_BASE_URL,
            api_key=_settings.DEEPSEEK_API_KEY,
            model=_settings.PRIMARY_MODEL,
            temperature=0.1,
            max_tokens=1500,
        )

        prompt = f"""Based on this RFP analysis, generate a CRM support ticket.

CONTEXT:
{context_text}

Return ONLY JSON (no markdown):
{{{{
  "issue_summary": "one-line summary of the client's request",
  "issue_category": "procurement|technical|contract|general",
  "relevant_context": "key facts for the support team (2-3 sentences)",
  "suggested_resolution": "recommended next steps (2-3 sentences)",
  "confidence": "high|medium|low"
}}}}"""

        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.THINKING,
            content="Generating ticket fields via DeepSeek..."
        ))

        response = await llm.ainvoke(prompt)
        raw = str(response.content) if hasattr(response, "content") else str(response)

        # Parse JSON
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        for fence in ("```json", "```"):
            if fence in raw:
                raw = raw.split(fence)[1].split("```")[0].strip()
                break
        start_idx, end_idx = raw.find("{"), raw.rfind("}") + 1
        ticket_data = {}
        if start_idx != -1 and end_idx > start_idx:
            try:
                ticket_data = json.loads(raw[start_idx:end_idx])
            except json.JSONDecodeError:
                pass

        # Attach conflict report from requirements (TWIST 2)
        conflict_report = None
        if requirements and requirements.conflict_report:
            conflict_report = requirements.conflict_report

        return SupportTicket(
            ticket_id=f"TKT-{_uuid.uuid4().hex[:8].upper()}",
            client_company=requirements.issuing_company if requirements else (rfp_input.company_name if rfp_input else ""),
            issue_summary=ticket_data.get("issue_summary", f"RFP response required: {requirements.project_name if requirements else 'Unknown'}"),
            issue_category=ticket_data.get("issue_category", "procurement"),
            relevant_context=ticket_data.get("relevant_context", context_text[:500]),
            suggested_resolution=ticket_data.get("suggested_resolution", "Prepare and submit quotation before deadline."),
            conflict_report=conflict_report,
            confidence=ticket_data.get("confidence", "medium"),
            auto_generated=True,
            created_at=datetime.now().isoformat(),
        )

    async def _node_approve_gate(self, state: GraphState, config: RunnableConfig):
        """Dummy node simply to act as the interception block edge before PDF creation."""
        pass

    def _route_feedback(self, state: GraphState) -> str:
        """Determine downstream node to hit back to based on feedback payload."""
        feedback = state.get("feedback")
        if not feedback:
            return "pdf_generator"  # Graceful fallback, though mathematically unreachable without approval
            
        if feedback.approved and not feedback.changes:
            return "pdf_generator"
            
        # Target lowest-level agent first (Linear downstream forces recomputation cleanly)
        targets = [c.target_agent for c in feedback.changes]
        if AgentRole.JUNIOR_ANALYST in targets:
            return "junior_analyst"
        if AgentRole.PRICING_STRATEGIST in targets:
            return "pricing_strategist"
        if AgentRole.SENIOR_COPYWRITER in targets:
            return "senior_copywriter"
            
        return "pdf_generator"

    async def _node_pdf_generator(self, state: GraphState, config: RunnableConfig):
        emit = config["configurable"].get("emit") or _noop_emit

        # ── Compliance Validation (Section 10 of design doc) ──
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.STATUS,
            content="🔍 Running compliance validation before PDF generation..."
        ))

        try:
            compliance_report = validate_proposal_compliance(
                requirements=state["extracted_requirements"],
                pricing=state["pricing_strategy"],
                proposal=state["proposal_draft"],
            )

            for risk in compliance_report.get("risks", []):
                await emit(AgentMessage(
                    agent=AgentRole.ORCHESTRATOR,
                    message_type=MessageType.ERROR,
                    content=f"⚠️ COMPLIANCE RISK: {risk}"
                ))
            for warning in compliance_report.get("warnings", []):
                await emit(AgentMessage(
                    agent=AgentRole.ORCHESTRATOR,
                    message_type=MessageType.THINKING,
                    content=f"⚡ COMPLIANCE WARNING: {warning}"
                ))

            checks = compliance_report.get("checks_performed", 0)
            clauses = compliance_report.get("compliance_clauses_found", 0)
            status = "PASSED" if compliance_report.get("passed") else "RISKS DETECTED"
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.RESULT,
                content=f"Compliance check complete: {checks} checks performed, "
                        f"{clauses} mandatory clauses identified. Status: {status}"
            ))
        except Exception as e:
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.THINKING,
                content=f"Compliance validation skipped: {str(e)}"
            ))

        # ── PDF Generation ──
        await emit(AgentMessage(
            agent=AgentRole.PDF_GENERATOR,
            message_type=MessageType.STATUS,
            content="📄 Generating boardroom-ready PDF quotation..."
        ))

        try:
            pdf_path = await asyncio.to_thread(
                self.pdf_generator.generate,
                job_id=state["job_id"],
                requirements=state["extracted_requirements"],
                pricing=state["pricing_strategy"],
                proposal=state["proposal_draft"],
                company_name=state["rfp_input"].company_name,
                contact_name=state["rfp_input"].contact_name,
                contact_email=state["rfp_input"].contact_email,
                contact_phone=state["rfp_input"].contact_phone,
            )
            
            await emit(AgentMessage(
                agent=AgentRole.PDF_GENERATOR,
                message_type=MessageType.COMPLETE,
                content="✅ PDF quotation generated successfully! Ready for download."
            ))
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.COMPLETE,
                content="🎉 RFP processing complete! Your professional quotation is ready."
            ))
            return {"pdf_path": pdf_path, "status": JobStatus.COMPLETED}
        except Exception as e:
            await emit(AgentMessage(
                agent=AgentRole.PDF_GENERATOR,
                message_type=MessageType.ERROR,
                content=f"Error generating PDF: {str(e)}"
            ))
            return {"status": JobStatus.ERROR}


# Singleton instance
orchestrator = Orchestrator()
