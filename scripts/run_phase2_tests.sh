#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-./venv/bin/python}"

echo "Running AIService unit tests..."
"$PYTHON_BIN" tests/test_ai_service.py

echo
echo "Running SEOService unit tests..."
"$PYTHON_BIN" tests/test_seo_service.py

echo
echo "Running Phase 2 integration tests..."
"$PYTHON_BIN" tests/test_phase2_integration.py

echo
echo "Running full test discovery..."
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'
