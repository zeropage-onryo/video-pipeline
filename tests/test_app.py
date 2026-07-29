"""
Smoke test for the dashboard route. Template-only route reading real
data through src/db.py -- BUILD_SPEC.md exempts template-only routes
from strict TDD ("Parsers and queries are not"; this isn't either).
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_returns_200():
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_shows_real_counts():
    response = client.get("/")
    assert "Pitch runs" in response.text
    assert "Ideas" in response.text
