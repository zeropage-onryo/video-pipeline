#!/bin/bash
cd "$(dirname "$0")/../.." || exit 1
LOG="data/_to_delete/install.log"
: > "$LOG"
{
  echo "=== $(date) ==="
  echo "Installing ONLY the two missing packages -- not -r requirements.txt,"
  echo "which would re-resolve everything and could upgrade fastapi/starlette/"
  echo "langgraph under the server that is currently running on :8000."
  echo
  venv/bin/pip install "mcp>=2" pillow-heif 2>&1 | tail -25
  echo
  echo "=== did anything ELSE change version? (should be empty) ==="
  venv/bin/pip check 2>&1 | tail -5
  echo
  echo "=== both import now? ==="
  venv/bin/python -c "import mcp, pillow_heif; print('mcp', mcp.__version__ if hasattr(mcp,'__version__') else 'ok'); print('pillow_heif ok')" 2>&1 | tail -5
  echo
  echo "=== the five that were failing ==="
  venv/bin/python -m pytest -q tests/test_mcp_server.py 2>&1 | tail -6
  echo
  echo "=== whole suite ==="
  venv/bin/python -m pytest -q tests/ 2>&1 | tail -8
  echo
  echo "=== ruff ==="
  venv/bin/python -m ruff check src/ app/ ops/ tests/ 2>&1 | tail -3
  echo "=== DONE ==="
} >> "$LOG" 2>&1
