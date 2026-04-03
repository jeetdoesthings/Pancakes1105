#!/bin/bash

# Ensure Homebrew libraries are discoverable by WeasyPrint's cffi on macOS
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH

echo "🚀 Starting SME02 Autonomous RFP Orchestrator..."
echo "✅ DYLD_FALLBACK_LIBRARY_PATH configured for WeasyPrint"

# Activate virtual environment
source venv/bin/activate

# Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000
