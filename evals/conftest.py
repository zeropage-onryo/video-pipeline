"""
evals/ is deliberately NOT under tests/ -- tests/conftest.py's
no_network fixture is autouse within its own directory tree and would
block every real Gemini judge call this suite depends on. Keeping the
eval suite as a sibling directory means `pytest tests/` (or a bare
`pytest` in CI's unit-test job) stays fully hermetic and never
accidentally spends money, while `pytest evals/` is the one place in
this repo that's expected to make real API calls and cost real money.

Skips the whole directory with one clear reason -- rather than N
confusing per-test failures -- when no Gemini key is present, so a
contributor without one (or a fork's CI run with no secret) gets a
skip, not a wall of connection errors.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

# deepeval phones home to PostHog/Sentry by default; this is an eval
# harness for a one-person project, not something to silently opt
# into telemetry for.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return
    skip = pytest.mark.skip(reason="GEMINI_API_KEY not set -- evals/ needs a real judge model")
    for item in items:
        item.add_marker(skip)
