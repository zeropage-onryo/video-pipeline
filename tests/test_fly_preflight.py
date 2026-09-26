"""The production container must fail before booting with unsafe config."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "fly" / "preflight.sh"


def configured_env(**overrides: str) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "DATABASE_URL": "postgresql://example.test/postgres",
        "RAG_DATABASE_URL": "postgresql://example.test/postgres",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "SESSION_SECRET": "test-session-secret",
        "SITE_URL": "https://example.fly.dev",
    }
    env.update(overrides)
    return env


def run_preflight(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_names_missing_secrets_without_printing_values():
    result = run_preflight({"PATH": os.environ["PATH"]})

    assert result.returncode == 1
    assert "DATABASE_URL" in result.stderr
    # the BYOK key secret is no longer required (per-account keys were
    # removed 2026-09-26), so a machine without it boots
    assert "ACCOUNT_KEYS_SECRET" not in result.stderr


def test_preflight_accepts_public_supabase_configuration():
    result = run_preflight(configured_env())

    assert result.returncode == 0
    assert "deployment configuration: ok" in result.stdout
    assert "no Gemini key" in result.stderr
    assert "no FAL_KEY" in result.stderr        # warned, never refused
    ok = run_preflight(configured_env(FAL_KEY="k", GEMINI_API_KEY="g"))
    assert ok.returncode == 0 and "FAL_KEY" not in ok.stderr


def test_preflight_refuses_public_dev_console():
    result = run_preflight(configured_env(DEV_TOOLS="1"))

    assert result.returncode == 1
    assert "DEV_TOOLS=1 is refused" in result.stderr


def test_fly_health_probe_is_public_and_minimal():
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
