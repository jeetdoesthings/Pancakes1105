#!/usr/bin/env bash

set -euo pipefail

echo "Starting SME02 Autonomous RFP Orchestrator..."

if [ -f ".venv/bin/activate" ]; then
	# Preferred virtual environment path.
	source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
	source venv/bin/activate
else
	echo "No virtual environment found (.venv or venv)."
	exit 1
fi

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
