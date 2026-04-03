
# QuotientAI — Final Build Context & Agentic Development Guide

**Product Name:** QuotientAI  
**System Type:** Production-style SaaS MVP  
**Architecture:** Multi-Agent Workflow using LangGraph  
**Build Strategy:** Backend First → Frontend Later  
**Primary Goal:** Build a reliable, intelligent, production-feeling system that wins demos and scales to real deployment.

---

# 1. Product Definition

QuotientAI is an autonomous quotation and proposal generation system for businesses responding to RFPs.

The system:

1. Accepts an uploaded RFP document
2. Extracts structured requirements using an LLM
3. Validates extracted data
4. Retrieves competitor pricing
5. Computes a pricing strategy
6. Applies MATCH or PIVOT decision logic
7. Pauses for human approval
8. Generates a professional PDF quotation

This is **not a chatbot**.  
This is **not a text generator**.  
This is a **production-style SaaS workflow system**.

---

# 2. Core System Principles

Every module must support:

## Intelligence
System makes explainable pricing decisions.

## Trust
System validates outputs and handles failures safely.

## Control
Human approval is mandatory before final output.

---

# 3. Technology Stack (Final)

Backend:

- Python 3.10+
- FastAPI
- LangGraph
- LangChain
- Ollama
- ReportLab
- PyMuPDF
- Pydantic

LLM:

- Runtime: Ollama
- Model: Mistral 7B Instruct
- Fallback: Llama 3 8B

Frontend (later):

- Next.js
- Tailwind
- TypeScript

---

# 4. Orchestration Framework (Mandatory)

Use **LangGraph**.

Do NOT build a custom state machine.

Workflow DAG:

RFP Analyst  
→ Validation Guardrail  
→ Market Scout  
→ Pricing Strategist  
→ Human Approval Gate  
→ Proposal Architect  
→ END

Implementation rule:

Each agent:

- accepts AgentState
- returns AgentState

Use:

StateGraph(AgentState)

Use:

add_node  
add_edge  
add_conditional_edges

---

# 5. LLM Configuration

Runtime:

Ollama

Model:

mistral

Timeout:

30 seconds

Temperature:

Extraction:

0.1

Rationale:

0.3

Config:

OLLAMA_BASE_URL=http://localhost:11434  
OLLAMA_MODEL=mistral  
LLM_TIMEOUT_SECONDS=30  

Fallback rule:

If LLM fails:

Use predefined fallback data.

Never block the workflow.

---

# 6. Demo Data (Module 0 — Must Create First)

Create:

backend/data/demo_rfp_pivot.pdf  
backend/data/demo_rfp_match.pdf  

Pivot RFP must trigger:

Competitor price < internal cost

Match RFP must trigger:

Competitor price ≥ internal cost

This guarantees deterministic demo behavior.

---

# 7. Feature Tiers

## Tier 1 — Demo Critical

Must be completed first.

- Upload RFP
- Extract text
- Validate data
- Load competitor data
- Compute pricing decision
- MATCH / PIVOT logic
- Human approval
- PDF generation
- Download PDF
- Log streaming
- Health endpoint

## Tier 2 — Impressive

Build after Tier 1 is stable.

- Confidence scoring
- Missing field detection
- Reviewer notes
- Multi-currency
- Tax calculation
- Audit trail

## Tier 3 — Optional

Only if ahead of schedule.

- Self-correction loop
- Retry logic
- Timing metrics
- Demo mode toggle
- Dynamic market simulation

Rule:

Never start Tier 2 before Tier 1 is stable.  
Never start Tier 3 before Tier 2 is stable.

---

# 8. Shared AgentState Schema

Required fields:

task_id  
workflow_status  
rfp_text  
rfp_data  
rfp_confidence  
validation_errors  
market_intel  
pricing_decision  
approved_pricing  
human_feedback  
agent_logs  
pdf_path  
created_at  
updated_at  
error  

Workflow statuses:

processing  
awaiting_approval  
approved  
rejected  
completed  
failed  

---

# 9. Business Logic Rules

## MATCH

If:

competitor price ≥ internal cost

Then:

undercut slightly  
maintain minimum margin  

## PIVOT

If:

competitor price < internal cost

Then:

switch to value-add strategy  
add premium bundle  
maintain sustainable margin  

---

# 10. Error Handling Rules

System must handle:

- invalid PDF
- empty extraction
- LLM timeout
- invalid JSON
- missing competitor
- PDF failure
- approval duplication
- task not found

System must:

- log the failure
- return clear message
- continue safely

Never crash silently.

---

# 11. API Contract (Backend)

Health:

GET /health

Upload:

POST /upload-rfp

Logs:

GET /stream-logs/{task_id}

State:

GET /task-state/{task_id}

Approve:

POST /approve/{task_id}

Reject:

POST /reject/{task_id}

Download:

GET /download-pdf/{task_id}

---

# 12. Frontend Integration Contract

Upload response:

{
  task_id: string,
  message: string
}

Log stream format:

data: {
  agent,
  message,
  timestamp,
  type
}

Status change event:

event: status

Task state:

Full AgentState JSON

Approve request:

{
  adjusted_price?: number,
  feedback?: string
}

Reject request:

{
  feedback?: string
}

---

# 13. Backend Folder Structure

backend/

app/
core/
models/
services/
workflow/
api/
utils/

data/
output/
tests/

This structure must remain stable.

---

# 14. Logging Standard

Every log must include:

timestamp  
agent  
event  
message  

Example:

{
  "timestamp": "2026-01-10T14:32:18",
  "agent": "Pricing Strategist",
  "event": "PIVOT_DETECTED",
  "message": "Competitor below internal cost"
}

---

# 15. Development Order (Strict)

Module 0 — Demo data  
Module 1 — Project skeleton  
Module 2 — PDF parsing  
Module 3 — RFP analyst  
Module 4 — Validation guardrail  
Module 5 — Market scout  
Module 6 — Pricing strategist  
Module 7 — Workflow engine  
Module 8 — Approval APIs  
Module 9 — PDF generation  
Module 10 — Logs & state  
Module 11 — Hardening  

---

# 16. Build Rules for All Coding Agents

Always:

Read this file before coding.

Do:

Build module by module.  
Keep architecture modular.  
Use LangGraph workflow.  
Use deterministic fallbacks.  
Log every step.  
Protect the approval gate.  

Never:

Redesign architecture  
Add unnecessary frameworks  
Skip validation  
Break workflow  
Build frontend early  

---

# 17. Acceptance Criteria

Backend is complete only when:

Upload works  
Extraction works  
Validation works  
Pricing decision works  
Approval pause works  
PDF generates  
PDF downloads  
Logs stream  
State endpoint works  
Errors handled safely  

---

# 18. Final Mission

Build QuotientAI like a real SaaS product:

Reliable  
Explainable  
Observable  
Controllable  
Demo-safe  
Production-feeling

Frontend comes later.

Backend is the foundation.
