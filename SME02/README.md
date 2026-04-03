# SME02: Autonomous RFP Response & Competitive Quotation Orchestrator

An AI-powered multi-agent system that automates the Request for Proposal (RFP) response process for Small and Medium Enterprises (SMEs), enabling them to generate professional, strategically priced quotations in minutes rather than days.

## Features

- **Multi-Agent Framework**: Three specialized agents working in concert
  - **Junior Analyst**: Parses unstructured RFP documents and extracts key requirements
  - **Pricing Strategist**: Analyzes internal pricing, competitor data, and applies value-differentiation strategies
  - **Senior Copywriter**: Drafts professional proposal content

- **Intelligent Value-Differentiation**: When competitors undercut on price, the system recommends non-monetary value-adds instead of racing to the bottom

- **Glass Box UI**: Real-time visibility into agent reasoning and decision-making

- **Boardroom-Ready PDF Output**: Professional, formatted quotation documents

## Tech Stack

- **Backend**: FastAPI (Python)
- **Multi-Agent Framework**: LangChain
- **LLM**: Google Gemini API (Free Tier)
- **PDF Generation**: WeasyPrint
- **Frontend**: Vanilla HTML/CSS/JavaScript

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up your Google Gemini API key:
```bash
export GEMINI_API_KEY=your_api_key_here
```

3. Run the application:
```bash
uvicorn app.main:app --reload
```

4. Open http://localhost:8000 in your browser

## Project Structure

```
SME02/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── junior_analyst.py    # RFP parsing agent
│   │   ├── pricing_strategist.py # Pricing analysis agent
│   │   └── senior_copywriter.py  # Proposal drafting agent
│   ├── services/
│   │   ├── __init__.py
│   │   ├── pdf_generator.py     # PDF generation service
│   │   └── orchestrator.py      # Multi-agent orchestrator
│   └── templates/
│       └── quotation.html       # PDF template
├── data/
│   ├── internal_pricing.json    # Mock internal pricing data
│   └── competitor_data.json     # Mock competitor data
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
├── requirements.txt
└── README.md
```

## License

MIT
