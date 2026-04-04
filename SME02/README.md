# SME02: Autonomous RFP Response & Competitive Quotation Orchestrator

An AI-powered multi-agent system that automates the Request for Proposal (RFP) response process for Small and Medium Enterprises (SMEs), enabling them to generate professional, strategically priced quotations in minutes rather than days.

## 🚀 Key Upgrades (v2.0)
- **Dependency-Light PDF Engine**: Migrated from WeasyPrint to **xhtml2pdf + Jinja2 templates**, avoiding system-level Pango/Cairo setup and improving cross-platform reliability.
- **Hybrid LLM Routing**: Uses **Gemini (primary)** plus **Groq-hosted Llama (fast/fallback)** for balanced quality and speed.
- **Windows Stability**: Hardened UTF-8 encoding across the streaming backend to support global currency symbols (₹, $, €) without crashes.

## 🤖 Multi-Agent Framework
The system uses a sequential DAG (Directed Acyclic Graph) powered by **LangGraph**:
1. **Junior Analyst**: Parses unstructured RFP documents and extracts key requirements with intelligent data normalization.
2. **Pricing Strategist**: Analyzes internal pricing and competitor data, applying value-differentiation strategies when undercut.
3. **Senior Copywriter**: Drafts persuasive, professional proposal content based on the final strategy.

## 🛠️ Tech Stack
- **Backend**: FastAPI (Python 3.10+)
- **Orchestration**: LangChain & LangGraph
- **LLM**: Gemini (primary) + Groq Llama (fallback/fast)
- **PDF Generation**: xhtml2pdf + Jinja2 (Template-Driven Layout)
- **Frontend**: Glassmorphic Vanilla Web Components (HTML/CSS/JS)

## 📦 Setup & Installation

1. **Clone & Install Dependencies**:
```bash
cd SME02
pip install -r requirements.txt
```

2. **Configure Environment**:
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
PRIMARY_MODEL=gemini-2.5-flash
FAST_MODEL=llama-3.3-70b-versatile
ESTIMATOR_MODEL=llama-3.1-8b-instant
# Optional for vector embeddings (otherwise lexical fallback is used):
# OPENAI_API_KEY=sk-...
# Optional: DEBUG=true for hot reload (defaults to false)
# MAX_UPLOAD_BYTES=15728640
# MAX_RFP_TEXT_CHARS=2000000
```

3. **Run the Application**:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

4. **Access the Dashboard**:
Open [http://localhost:8000](http://localhost:8000) in your browser.

## 📁 Project Structure
```
SME02/
├── app/
│   ├── main.py              # FastAPI Entry Point (UTF-8 Hardened)
│   ├── agents/              # Specialist AI Agents
│   ├── services/
│   │   ├── pdf_generator.py # xhtml2pdf Quotation Engine
│   │   └── orchestrator.py  # LangGraph Orchestration Logic
│   └── models.py            # Pydantic Core Models
├── data/                    # Mock Pricing & Competitor Data
├── output/                  # Runtime-generated quotation PDFs
├── scripts/                 # Utility scripts (e.g., PDF smoke generation)
├── static/                  # Glassmorphic Frontend
├── requirements.txt         # Optimized Dependency List
└── README.md                # Documentation
```

## 📄 License
MIT
