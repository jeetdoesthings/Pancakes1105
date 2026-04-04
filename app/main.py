"""
SME02 FastAPI Application
=========================
Main application entry point. Provides REST API endpoints
with Server-Sent Events (SSE) for real-time agent reasoning.
"""

import asyncio
import json
import os
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import (
    RFPInput, HumanFeedback, AgentMessage, JobStatus,
    AgentRole, MessageType
)
from app.services.orchestrator import orchestrator
from app.services.document_parser import document_parser

app = FastAPI(
    title="SME02 — Autonomous RFP Response Orchestrator",
    description="AI-powered multi-agent system for competitive quotation generation",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


# ---- Utilities ----

class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle date/datetime objects."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# ---- Serve Frontend ----

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = os.path.join(settings.STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ---- API Endpoints ----

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
    contact_phone: str = Form(default="+91-9876543210")
):
    """Upload an RFP document, extract text, and start processing."""
    file_bytes = await file.read()
    
    try:
        extracted_text = document_parser.extract_text(file.filename, file_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Document appears to be empty or unreadable.")
        
    rfp_input = RFPInput(
        rfp_text=extracted_text,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone
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
        # Start processing in background
        process_task = asyncio.create_task(
            orchestrator.process_rfp(job_id, emit_message=emit_message)
        )

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                    data = json.dumps({
                        "agent": msg.agent.value if hasattr(msg.agent, "value") else str(msg.agent),
                        "type": msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type),
                        "content": msg.content,
                        "timestamp": msg.timestamp or datetime.now().isoformat(),
                    }, cls=DateTimeEncoder, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Check if process task is done
                    if process_task.done():
                        # Wait a moment for any final messages
                        await asyncio.sleep(0.5)
                        
                        # Drain remaining messages
                        while not message_queue.empty():
                            msg = await message_queue.get()
                            data = json.dumps({
                                "agent": msg.agent.value if hasattr(msg.agent, "value") else str(msg.agent),
                                "type": msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type),
                                "content": msg.content,
                                "timestamp": msg.timestamp or datetime.now().isoformat(),
                            }, cls=DateTimeEncoder, ensure_ascii=False)
                            yield f"data: {data}\n\n"

                        # Get job status - try multiple times with delay
                        for _ in range(5):
                            job = orchestrator.get_job(job_id)
                            if job and job.status:
                                break
                            await asyncio.sleep(0.2)
                        
                        if job and job.status:
                            final_data = json.dumps({
                                "agent": "Orchestrator",
                                "type": "job_state",
                                "content": "",
                                "timestamp": datetime.now().isoformat(),
                                "job_status": job.status.value,
                                "extracted_requirements": job.extracted_requirements.model_dump() if job.extracted_requirements else None,
                                "universal_rfp": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("universal_rfp"),
                                "similar_rfps": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("similar_rfps"),
                                "pricing_strategy": job.pricing_strategy.model_dump() if job.pricing_strategy else None,
                                "proposal_draft": job.proposal_draft.model_dump() if job.proposal_draft else None,
                            }, cls=DateTimeEncoder, ensure_ascii=False)
                            yield f"data: {final_data}\n\n"
                            await asyncio.sleep(1.0)
                        break
                    yield f": keepalive\n\n"
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
        }
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
        # Direct approval – generate PDF
        result = await orchestrator.approve_and_generate(job_id)
        return {
            "status": result.status.value,
            "pdf_ready": result.pdf_path is not None,
            "job_id": job_id,
        }

    return {"status": "changes_received", "job_id": job_id, "message": "Use /api/revise/{job_id} SSE endpoint to process changes."}


@app.get("/api/revise/{job_id}")
async def stream_revision(job_id: str, feedback_json: Optional[str] = None):
    """SSE endpoint — streams agent re-processing after feedback."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get stored feedback
    feedback_data = json.loads(feedback_json) if feedback_json else {"approved": False, "changes": []}
    feedback = HumanFeedback(**feedback_data)

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
                    data = json.dumps({
                        "agent": msg.agent.value if hasattr(msg.agent, "value") else str(msg.agent),
                        "type": msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type),
                        "content": msg.content,
                        "timestamp": msg.timestamp or datetime.now().isoformat(),
                    }, cls=DateTimeEncoder, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if process_task.done():
                        final_job = orchestrator.get_job(job_id)
                        final_data = json.dumps({
                            "agent": "Orchestrator",
                            "type": "job_state",
                            "content": "",
                            "timestamp": datetime.now().isoformat(),
                            "job_status": final_job.status.value,
                            "extracted_requirements": final_job.extracted_requirements.model_dump() if final_job.extracted_requirements else None,
                            "universal_rfp": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("universal_rfp"),
                            "similar_rfps": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("similar_rfps"),
                            "pricing_strategy": final_job.pricing_strategy.model_dump() if final_job.pricing_strategy else None,
                            "proposal_draft": final_job.proposal_draft.model_dump() if final_job.proposal_draft else None,
                        }, cls=DateTimeEncoder, ensure_ascii=False)
                        yield f"data: {final_data}\n\n"
                        break
                    yield f": keepalive\n\n"
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
        }
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
                    data = json.dumps({
                        "agent": msg.agent.value if hasattr(msg.agent, "value") else str(msg.agent),
                        "type": msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type),
                        "content": msg.content,
                        "timestamp": msg.timestamp or datetime.now().isoformat(),
                    }, cls=DateTimeEncoder, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if process_task.done():
                        final_job = orchestrator.get_job(job_id)
                        final_data = json.dumps({
                            "agent": "Orchestrator",
                            "type": "job_state",
                            "content": "",
                            "timestamp": datetime.now().isoformat(),
                            "job_status": final_job.status.value,
                            "pdf_ready": final_job.pdf_path is not None,
                            "universal_rfp": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("universal_rfp"),
                            "similar_rfps": orchestrator.graph.get_state({"configurable": {"thread_id": job_id}}).values.get("similar_rfps"),
                        }, cls=DateTimeEncoder, ensure_ascii=False)
                        yield f"data: {final_data}\n\n"
                        break
                    yield f": keepalive\n\n"
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
        }
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
        "Cache-Control": "no-cache"
    }

    return FileResponse(
        job.pdf_path,
        media_type="application/pdf",
        filename=f"SME02_Quotation_{job_id}.pdf",
        headers=headers
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


# ---- Health Check ----

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
