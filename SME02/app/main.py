"""
SME02 FastAPI Application
=========================
Main application entry point. Provides REST API endpoints
with Server-Sent Events (SSE) for real-time agent reasoning.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import settings
from app.db import init_db
from app.models import (
    RFPInput, HumanFeedback, AgentMessage, JobStatus,
    AgentRole, MessageType
)
from app.services.orchestrator import orchestrator
from app.services.document_parser import document_parser

logger = logging.getLogger(__name__)


def _agent_message_payload(msg: AgentMessage) -> dict:
    return {
        "agent": msg.agent.value if hasattr(msg.agent, "value") else str(msg.agent),
        "type": msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type),
        "content": msg.content,
        "timestamp": msg.timestamp or datetime.now().isoformat(),
    }


def _job_state_dict(job) -> dict:
    return {
        "agent": "Orchestrator",
        "type": "job_state",
        "content": "",
        "timestamp": datetime.now().isoformat(),
        "job_status": job.status.value,
        "extracted_requirements": job.extracted_requirements.model_dump() if job.extracted_requirements else None,
        "pricing_strategy": job.pricing_strategy.model_dump() if job.pricing_strategy else None,
        "proposal_draft": job.proposal_draft.model_dump() if job.proposal_draft else None,
    }


def _approve_job_state_dict(job) -> dict:
    d = _job_state_dict(job)
    d["pdf_ready"] = job.pdf_path is not None
    return d


def _resolve_revision_feedback(job_id: str, feedback_json: Optional[str]) -> HumanFeedback:
    """Prefer POST-queued feedback; fall back to legacy `feedback_json` query parameter."""
    queued = orchestrator.pop_pending_feedback(job_id)
    if queued is not None:
        return queued
    if feedback_json:
        try:
            data = json.loads(feedback_json)
            return HumanFeedback.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid feedback: {e}") from e
    raise HTTPException(
        status_code=400,
        detail="Revision feedback required: POST JSON to /api/revise/{job_id} or pass feedback_json (legacy query).",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is not set — primary model calls will fail until configured.")
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY is not set — fallback/fast model calls will fail until configured.")
    if not settings.OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY is not set — vector embeddings will use lexical fallback mode.")
    yield


app = FastAPI(
    title="SME02 — Autonomous RFP Response Orchestrator",
    description="AI-powered multi-agent system for competitive quotation generation",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: wildcard origin is incompatible with credentials in browsers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = os.path.join(settings.STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/process-rfp")
async def process_rfp(rfp_input: RFPInput):
    """Start processing an RFP from raw text."""
    job_id = orchestrator.create_job(rfp_input)
    return {"job_id": job_id, "status": "created"}


@app.post("/api/upload-rfp")
async def upload_rfp(
    file: UploadFile = File(...),
    company_name: str = Form(default="Ering Solutions"),
    contact_name: str = Form(default="Sales Team"),
    contact_email: str = Form(default="sales@eringsolutions.com"),
    contact_phone: str = Form(default="+91-9876543210"),
):
    """Upload an RFP document, extract text, and start processing."""
    file_bytes = await file.read()
    max_b = settings.MAX_UPLOAD_BYTES
    if len(file_bytes) > max_b:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(file_bytes)} bytes). Maximum allowed is {max_b} bytes.",
        )

    try:
        extracted_text = document_parser.extract_text(file.filename, file_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Document appears to be empty or unreadable.")

    rfp_input = RFPInput(
        rfp_text=extracted_text,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )

    job_id = orchestrator.create_job(rfp_input)
    return {"job_id": job_id, "status": "created"}


@app.get("/api/stream/{job_id}")
async def stream_processing(job_id: str):
    """SSE endpoint — streams agent reasoning messages in real-time."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    message_queue: asyncio.Queue = asyncio.Queue()

    async def emit_message(msg: AgentMessage):
        await message_queue.put(msg)

    async def event_generator():
        process_task = asyncio.create_task(
            orchestrator.process_rfp(job_id, emit_message=emit_message)
        )

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    data = json.dumps(_agent_message_payload(msg), ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if process_task.done():
                        final_job = orchestrator.get_job(job_id)
                        final_data = json.dumps(_job_state_dict(final_job), ensure_ascii=False)
                        yield f"data: {final_data}\n\n"

                        while not message_queue.empty():
                            msg = await message_queue.get()
                            data = json.dumps(_agent_message_payload(msg), ensure_ascii=False)
                            yield f"data: {data}\n\n"

                        break
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            process_task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/feedback/{job_id}")
async def submit_feedback(job_id: str, feedback: HumanFeedback):
    """Submit human feedback — approve or request changes."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=400, detail=f"Job not in approval state (current: {job.status})")

    if feedback.approved and not feedback.changes:
        result = await orchestrator.approve_and_generate(job_id)
        return {
            "status": result.status.value,
            "pdf_ready": result.pdf_path is not None,
            "job_id": job_id,
        }

    return {
        "status": "changes_received",
        "job_id": job_id,
        "message": "POST feedback to /api/revise/{job_id}, then open GET /api/revise/{job_id} for the SSE stream.",
    }


@app.post("/api/revise/{job_id}")
async def submit_revision_feedback(job_id: str, feedback: HumanFeedback):
    """Queue revision feedback (large payloads). Call before opening the GET SSE stream."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.AWAITING_APPROVAL, JobStatus.REVISING):
        raise HTTPException(
            status_code=400,
            detail="Revisions are only accepted while the job awaits approval or is being revised.",
        )
    if not feedback.approved and not feedback.changes:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one change request, or approve via the approval flow.",
        )
    orchestrator.set_pending_feedback(job_id, feedback)
    return {"status": "queued", "job_id": job_id}


@app.get("/api/revise/{job_id}")
async def stream_revision(job_id: str, feedback_json: Optional[str] = None):
    """SSE — re-process after feedback (prefer POST /api/revise/{job_id} for the payload)."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    feedback = _resolve_revision_feedback(job_id, feedback_json)
    if not feedback.approved and not feedback.changes:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one change request, or approve via the approval flow.",
        )

    message_queue: asyncio.Queue = asyncio.Queue()

    async def emit_message(msg: AgentMessage):
        await message_queue.put(msg)

    async def event_generator():
        process_task = asyncio.create_task(
            orchestrator.handle_feedback(job_id, feedback, emit_message=emit_message)
        )

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    data = json.dumps(_agent_message_payload(msg), ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if process_task.done():
                        final_job = orchestrator.get_job(job_id)
                        final_data = json.dumps(_job_state_dict(final_job), ensure_ascii=False)
                        yield f"data: {final_data}\n\n"

                        while not message_queue.empty():
                            msg = await message_queue.get()
                            data = json.dumps(_agent_message_payload(msg), ensure_ascii=False)
                            yield f"data: {data}\n\n"

                        break
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            process_task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/approve/{job_id}")
async def approve_proposal(job_id: str):
    """Approve the proposal and generate PDF."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    message_queue: asyncio.Queue = asyncio.Queue()

    async def emit_message(msg: AgentMessage):
        await message_queue.put(msg)

    async def event_generator():
        process_task = asyncio.create_task(
            orchestrator.approve_and_generate(job_id, emit_message=emit_message)
        )

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    data = json.dumps(_agent_message_payload(msg), ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if process_task.done():
                        final_job = orchestrator.get_job(job_id)
                        final_data = json.dumps(_approve_job_state_dict(final_job), ensure_ascii=False)
                        yield f"data: {final_data}\n\n"
                        break
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            process_task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download-pdf/{job_id}")
async def download_pdf(job_id: str):
    """Download the generated PDF quotation."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.pdf_path:
        raise HTTPException(status_code=400, detail="PDF not generated yet")
    if not os.path.exists(job.pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    headers = {
        "Content-Disposition": f'attachment; filename="SME02_Quotation_{job_id}.pdf"',
        "Access-Control-Expose-Headers": "Content-Disposition",
        "Cache-Control": "no-cache",
    }

    return FileResponse(
        job.pdf_path,
        media_type="application/pdf",
        filename=f"SME02_Quotation_{job_id}.pdf",
        headers=headers,
    )


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get the current status of a job."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "revision_count": job.revision_count,
        "pdf_ready": job.pdf_path is not None,
        "extracted_requirements": job.extracted_requirements.model_dump() if job.extracted_requirements else None,
        "pricing_strategy": job.pricing_strategy.model_dump() if job.pricing_strategy else None,
        "proposal_draft": job.proposal_draft.model_dump() if job.proposal_draft else None,
    }


@app.get("/api/jobs")
async def list_jobs():
    """List all known job IDs with basic status information."""
    jobs = []
    for job_id in orchestrator.job_messages.keys():
        job = orchestrator.get_job(job_id)
        if job:
            project_name = ""
            if job.extracted_requirements:
                project_name = job.extracted_requirements.project_name or ""
            jobs.append({
                "job_id": job.job_id,
                "status": job.status.value,
                "project_name": project_name,
                "pdf_ready": job.pdf_path is not None,
                "revision_count": job.revision_count,
            })
    return {"jobs": jobs}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
