"""
Multi-Agent Orchestrator (LangGraph Edition)
============================================
Coordinates the three AI agents sequentially using LangGraph for robust 
state machines, human-in-the-loop breakpoints, and conditional routing.
"""

import uuid
import asyncio
from datetime import datetime
from typing import Callable, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_core.runnables import RunnableConfig

from app.models import (
    RFPInput, JobState, JobStatus, AgentMessage, AgentRole,
    MessageType, HumanFeedback, GraphState
)
from app.agents.junior_analyst import JuniorAnalyst
from app.agents.pricing_strategist import PricingStrategist
from app.agents.senior_copywriter import SeniorCopywriter
from app.services.pdf_generator import PDFGenerator


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

        self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(GraphState)

        # 1. Add Nodes
        workflow.add_node("junior_analyst", self._node_junior_analyst)
        workflow.add_node("pricing_strategist", self._node_pricing_strategist)
        workflow.add_node("senior_copywriter", self._node_senior_copywriter)
        workflow.add_node("approve_gate", self._node_approve_gate)
        workflow.add_node("pdf_generator", self._node_pdf_generator)

        # 2. Add Linear Edges
        workflow.add_edge(START, "junior_analyst")
        workflow.add_edge("junior_analyst", "pricing_strategist")
        workflow.add_edge("pricing_strategist", "senior_copywriter")
        workflow.add_edge("senior_copywriter", "approve_gate")

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
        return job_id

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
                pdf_path=state_values.get("pdf_path"),
                messages=self.job_messages.get(job_id, []),
                revision_count=state_values.get("revision_count", 0)
            )
        except Exception:
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
        emit = config["configurable"].get("emit")
        
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

        requirements, raw_dict = await self.junior_analyst.analyze(
            rfp_text=state["rfp_input"].rfp_text,
            emit_message=emit,
            additional_instructions=instructions
        )
        return {"extracted_requirements": requirements, "status": JobStatus.ANALYZING}

    async def _node_pricing_strategist(self, state: GraphState, config: RunnableConfig):
        emit = config["configurable"].get("emit")
        
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.ACTION,
            content="Activating Pricing Strategist agent for competitive analysis..."
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
        emit = config["configurable"].get("emit")
        
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
        emit = config["configurable"].get("emit")

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
