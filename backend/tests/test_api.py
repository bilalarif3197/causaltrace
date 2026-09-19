"""API surface tests, including the CORS policy.

The CORS tests exist because of a real incident: the app was opened through a
browser preview proxy on a different loopback port, every preflight was
rejected, and the frontend reported it as "cannot reach the API" -- which sent
debugging in entirely the wrong direction. Loopback origins on arbitrary ports
must work; non-loopback origins must not.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from services.llm_client import MockClient

client = TestClient(main.app)

PREFLIGHT_HEADERS = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:59004",  # a browser preview proxy
        "http://localhost:8080",
        "https://localhost:3000",
        "http://[::1]:3000",
    ],
)
def test_loopback_origins_are_allowed(origin):
    res = client.options("/api/analyze", headers={"Origin": origin, **PREFLIGHT_HEADERS})
    assert res.status_code == 200, f"{origin} should be allowed"
    assert res.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example.com",
        "https://causaltrace.attacker.io",
        "http://localhost.attacker.com",  # must not match the loopback pattern
        "http://127.0.0.1.attacker.com",
    ],
)
def test_non_loopback_origins_are_rejected(origin):
    res = client.options("/api/analyze", headers={"Origin": origin, **PREFLIGHT_HEADERS})
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers


def test_health_reports_mode_and_disclaimer():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["mode"] in {"live", "mock"}
    assert "not a medical device" in body["disclaimer"]
    assert "json_mode" in body


def test_examples_are_served():
    cases = client.get("/api/examples").json()
    assert len(cases) == 3
    assert any(c["is_ambiguous"] for c in cases), "at least one demo case must be ambiguous"
    for case in cases:
        assert case["narrative"].strip()
        assert case["suspected_drug"] and case["adverse_event"]


def test_analyze_validates_input():
    res = client.post("/api/analyze", json={"narrative": "", "suspected_drug": "", "adverse_event": ""})
    assert res.status_code == 422


def test_analyze_runs_a_builtin_case(monkeypatch):
    """Forced onto the mock client so the suite never makes a network call."""
    monkeypatch.setattr(main, "_client", MockClient())
    case = client.get("/api/examples").json()[0]
    res = client.post(
        "/api/analyze",
        json={
            "narrative": case["narrative"],
            "suspected_drug": case["suspected_drug"],
            "adverse_event": case["adverse_event"],
            "case_id": case["case_id"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["naranjo"]["classification"] in {"Definite", "Probable", "Possible", "Doubtful"}
    assert -4 <= body["naranjo"]["total_score"] <= 13
    assert len(body["naranjo"]["items"]) == 10
    # Offsets must slice back to the quoted text through the HTTP layer too.
    for claim in body["claims"]:
        span = claim["span"]
        if span and span["start"] is not None:
            assert body["narrative"][span["start"] : span["end"]] == span["text"]


def test_unrecorded_narrative_returns_422_in_mock_mode(monkeypatch):
    """Mock mode must fail with a clear explanation, not a 500."""
    monkeypatch.setattr(main, "_client", MockClient())
    res = client.post(
        "/api/analyze",
        json={
            "narrative": "A patient took a drug and felt unwell afterwards.",
            "suspected_drug": "Drug X",
            "adverse_event": "Nausea",
        },
    )
    assert res.status_code == 422
    assert "OPENAI_API_KEY" in res.json()["detail"]
