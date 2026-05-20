#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-./venv/bin/python}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-./.cache/matplotlib}"
mkdir -p "$MPLCONFIGDIR"

echo "Running PPTXService unit tests..."
"$PYTHON_BIN" tests/test_pptx_service.py

echo
echo "Running Phase 3 integration tests..."
"$PYTHON_BIN" tests/test_phase3_integration.py

echo
echo "Running full test discovery..."
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'
