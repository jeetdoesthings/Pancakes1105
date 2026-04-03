"""
Multi-Agent Orchestrator
========================
Coordinates the three AI agents sequentially, manages job state,
and handles human-in-the-loop feedback with targeted re-runs.
"""

import uuid
import asyncio
from datetime import datetime
from typing import Callable, Optional

from app.models import (
    RFPInput, JobState, JobStatus, AgentMessage, AgentRole,
    MessageType, HumanFeedback, ChangeRequest,
    ExtractedRequirements, PricingStrategy, ProposalDraft
)
from app.agents.junior_analyst import JuniorAnalyst
from app.agents.pricing_strategist import PricingStrategist
from app.agents.senior_copywriter import SeniorCopywriter
from app.services.pdf_generator import PDFGenerator


class Orchestrator:
    """Manages the multi-agent workflow for RFP processing."""

    def __init__(self):
        self.junior_analyst = JuniorAnalyst()
        self.pricing_strategist = PricingStrategist()
        self.senior_copywriter = SeniorCopywriter()
        self.pdf_generator = PDFGenerator()
        self.jobs: dict[str, JobState] = {}

    def create_job(self, rfp_input: RFPInput) -> str:
        """Create a new processing job."""
        job_id = str(uuid.uuid4())[:8]
        self.jobs[job_id] = JobState(
            job_id=job_id,
            status=JobStatus.PENDING,
            rfp_input=rfp_input,
        )
        return job_id

    def get_job(self, job_id: str) -> Optional[JobState]:
        return self.jobs.get(job_id)

    async def process_rfp(
        self,
        job_id: str,
        emit_message: Optional[Callable] = None,
    ) -> JobState:
        """Run all three agents sequentially, then present for approval."""
        job = self.jobs.get(job_id)
        if not job or not job.rfp_input:
            raise ValueError(f"Job {job_id} not found")

        async def emit(msg: AgentMessage):
            msg.timestamp = datetime.now().isoformat()
            job.messages.append(msg)
            if emit_message:
                await emit_message(msg)

        try:
            # --- Agent 1: Junior Analyst ---
            job.status = JobStatus.ANALYZING
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

            job.extracted_requirements = await self.junior_analyst.analyze(
                rfp_text=job.rfp_input.rfp_text,
                emit_message=emit,
            )

            # --- Agent 2: Pricing Strategist ---
            job.status = JobStatus.PRICING
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ACTION,
                content="Activating Pricing Strategist agent for competitive analysis..."
            ))

            job.pricing_strategy = await self.pricing_strategist.analyze(
                requirements=job.extracted_requirements,
                emit_message=emit,
            )

            # --- Agent 3: Senior Copywriter ---
            job.status = JobStatus.DRAFTING
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ACTION,
                content="Activating Senior Copywriter agent for proposal drafting..."
            ))

            job.proposal_draft = await self.senior_copywriter.draft(
                requirements=job.extracted_requirements,
                pricing=job.pricing_strategy,
                company_name=job.rfp_input.company_name,
                emit_message=emit,
            )

            # --- Awaiting Approval ---
            job.status = JobStatus.AWAITING_APPROVAL
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.STATUS,
                content="✅ All agents have completed their work. Proposal is ready for your review and approval."
            ))

        except Exception as e:
            job.status = JobStatus.ERROR
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ERROR,
                content=f"Error during processing: {str(e)}"
            ))

        return job

    async def handle_feedback(
        self,
        job_id: str,
        feedback: HumanFeedback,
        emit_message: Optional[Callable] = None,
    ) -> JobState:
        """Handle human feedback — re-run targeted agents if changes requested."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        async def emit(msg: AgentMessage):
            msg.timestamp = datetime.now().isoformat()
            job.messages.append(msg)
            if emit_message:
                await emit_message(msg)

        if feedback.approved and not feedback.changes:
            # Approved! Generate PDF
            return await self._generate_pdf(job, emit)

        # Process changes - identify which agents need to re-run
        job.status = JobStatus.REVISING
        job.revision_count += 1

        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.STATUS,
            content=f"📝 Processing your changes (Revision #{job.revision_count})..."
        ))

        # Group changes by target agent
        analyst_changes = [c for c in feedback.changes if c.target_agent == AgentRole.JUNIOR_ANALYST]
        strategist_changes = [c for c in feedback.changes if c.target_agent == AgentRole.PRICING_STRATEGIST]
        copywriter_changes = [c for c in feedback.changes if c.target_agent == AgentRole.SENIOR_COPYWRITER]

        # Re-run affected agents in order (downstream agents must re-run too)
        needs_analyst_rerun = len(analyst_changes) > 0
        needs_strategist_rerun = len(strategist_changes) > 0 or needs_analyst_rerun
        needs_copywriter_rerun = len(copywriter_changes) > 0 or needs_strategist_rerun

        if needs_analyst_rerun:
            instructions = "\n".join(c.instruction for c in analyst_changes)
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ACTION,
                content=f"Re-running Junior Analyst with your changes: {instructions}"
            ))
            job.status = JobStatus.ANALYZING
            job.extracted_requirements = await self.junior_analyst.analyze(
                rfp_text=job.rfp_input.rfp_text,
                emit_message=emit,
                additional_instructions=instructions,
            )

        if needs_strategist_rerun:
            instructions = "\n".join(c.instruction for c in strategist_changes)
            if needs_analyst_rerun:
                instructions += "\nNote: Requirements were updated by the Junior Analyst. Please re-analyze."
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ACTION,
                content=f"Re-running Pricing Strategist with your changes..."
            ))
            job.status = JobStatus.PRICING
            job.pricing_strategy = await self.pricing_strategist.analyze(
                requirements=job.extracted_requirements,
                emit_message=emit,
                additional_instructions=instructions,
            )

        if needs_copywriter_rerun:
            instructions = "\n".join(c.instruction for c in copywriter_changes)
            if needs_strategist_rerun:
                instructions += "\nNote: Pricing strategy was updated. Please incorporate the changes."
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.ACTION,
                content=f"Re-running Senior Copywriter with your changes..."
            ))
            job.status = JobStatus.DRAFTING
            job.proposal_draft = await self.senior_copywriter.draft(
                requirements=job.extracted_requirements,
                pricing=job.pricing_strategy,
                company_name=job.rfp_input.company_name,
                emit_message=emit,
                additional_instructions=instructions,
            )

        job.status = JobStatus.AWAITING_APPROVAL
        await emit(AgentMessage(
            agent=AgentRole.ORCHESTRATOR,
            message_type=MessageType.STATUS,
            content="✅ Revisions complete. Updated proposal is ready for your review."
        ))

        return job

    async def approve_and_generate(
        self,
        job_id: str,
        emit_message: Optional[Callable] = None,
    ) -> JobState:
        """Approve the proposal and generate the final PDF."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        async def emit(msg: AgentMessage):
            msg.timestamp = datetime.now().isoformat()
            job.messages.append(msg)
            if emit_message:
                await emit_message(msg)

        return await self._generate_pdf(job, emit)

    async def _generate_pdf(self, job: JobState, emit) -> JobState:
        """Generate the final PDF quotation."""
        job.status = JobStatus.GENERATING_PDF
        await emit(AgentMessage(
            agent=AgentRole.PDF_GENERATOR,
            message_type=MessageType.STATUS,
            content="📄 Generating boardroom-ready PDF quotation..."
        ))

        try:
            pdf_path = await asyncio.to_thread(
                self.pdf_generator.generate,
                job_id=job.job_id,
                requirements=job.extracted_requirements,
                pricing=job.pricing_strategy,
                proposal=job.proposal_draft,
                company_name=job.rfp_input.company_name,
                contact_name=job.rfp_input.contact_name,
                contact_email=job.rfp_input.contact_email,
                contact_phone=job.rfp_input.contact_phone,
            )
            job.pdf_path = pdf_path
            job.status = JobStatus.COMPLETED

            await emit(AgentMessage(
                agent=AgentRole.PDF_GENERATOR,
                message_type=MessageType.COMPLETE,
                content=f"✅ PDF quotation generated successfully! Ready for download."
            ))
            await emit(AgentMessage(
                agent=AgentRole.ORCHESTRATOR,
                message_type=MessageType.COMPLETE,
                content="🎉 RFP processing complete! Your professional quotation is ready."
            ))
        except Exception as e:
            job.status = JobStatus.ERROR
            await emit(AgentMessage(
                agent=AgentRole.PDF_GENERATOR,
                message_type=MessageType.ERROR,
                content=f"Error generating PDF: {str(e)}"
            ))

        return job


# Singleton instance
orchestrator = Orchestrator()
