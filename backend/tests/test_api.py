"""API surface tests for the review workspace.

Two things these lock down beyond plain routing:

  * There is no endpoint that turns a narrative into a verdict. Creating a
    case yields an empty workspace, and the Naranjo framework reads zero until
    a human answers something.
  * CORS accepts any loopback origin but nothing else. This regressed once
    already: a preview proxy on a different loopback port had every preflight
    rejected, and the frontend reported it as "cannot reach the API".

`main._client` is stubbed throughout, so the suite never spends tokens or
depends on a network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from schemas.review import ReviewerStatus

client = TestClient(main.app)

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}

NARRATIVE = (
    "A 34-year-old woman began TMP-SMX on March 2 for a urinary tract infection. "
    "Five days later she developed fatigue and nausea. On March 16 acute liver injury "
    "was identified with ALT 684 U/L."
)

STAGE_PAYLOADS = {
    "facts": {
        "facts": [
            {
                "field": "suspected_drug",
                "value": "TMP-SMX",
                "evidence_text": "began TMP-SMX on March 2",
                "confidence": 0.95,
            },
            {
                "field": "onset_date",
                "value": "March 7",
                "evidence_text": "Five days later she developed fatigue and nausea",
                "confidence": 0.9,
            },
            {
                "field": "lab_abnormalities",
                "value": "ALT 684 U/L",
                "evidence_text": "ALT 684 U/L",
                "confidence": 0.93,
            },
        ]
    },
    "verification": {
        "verdicts": [
            {"id": "*", "verdict": "SUPPORTED", "reason": "Quote states the claim."},
        ]
    },
    "timeline": {
        "events": [
            {
                "label": "TMP-SMX started",
                "category": "DRUG_START",
                "order": 1,
                "date_kind": "EXACT",
                "date_value": None,
                "display_date": "Mar 02",
                "relative_text": None,
                "actor": "TMP-SMX",
                "evidence_text": "began TMP-SMX on March 2",
            },
            {
                "label": "Fatigue and nausea",
                "category": "EVENT_ONSET",
                "order": 2,
                "date_kind": "RELATIVE",
                "date_value": None,
                "display_date": None,
                "relative_text": "Five days later",
                "actor": None,
                "evidence_text": "Five days later she developed fatigue and nausea",
            },
        ]
    },
    "dimensions": {
        "answers": [
            {
                "key": "exposure_before_event",
                "answer": "YES",
                "rationale": "Exposure on March 2 preceded onset.",
                "evidence_text": "began TMP-SMX on March 2",
                "confidence": 0.9,
            }
        ]
    },
    "hypotheses": {
        "hypotheses": [
            {
                "label": "TMP-SMX caused the liver injury",
                "kind": "SUSPECT_DRUG",
                "is_suspected_drug": True,
                "assessment": "Moderately supported",
                "rationale": "Temporal relationship fits.",
                "supporting": [
                    {"statement": "Exposure preceded onset.", "evidence_text": "began TMP-SMX on March 2"}
                ],
                "contradicting": [],
                "unknown": [{"statement": "No rechallenge performed.", "evidence_text": None}],
            }
        ]
    },
    "missing": {
        "items": [
            {
                "prompt": "Baseline liver function before exposure",
                "why_it_matters": "Distinguishes incident injury from pre-existing disease.",
                "affects": ["TMP-SMX"],
            }
        ]
    },
    "naranjo": {
        "items": [{"number": n, "answer": "UNKNOWN", "rationale": "", "evidence_text": None} for n in range(1, 11)]
    },
    "who_umc": {
        "classification": "Possible",
        "reasoning": "Temporal relationship present; alternatives not excluded.",
        "major_uncertainty": "No rechallenge.",
        "criteria": [],
        "supporting_evidence": [
            {"statement": "Exposure preceded onset.", "evidence_text": "began TMP-SMX on March 2"}
        ],
    },
    "rationale": {"rationale": "Draft rationale built from confirmed evidence."},
}


class StubClient:
    """Returns canned stage payloads; records which stages were asked for."""

    mode = "mock"
    name = "stub-client"
    active_json_mode = "strict"
    notes: list[str] = []

    def __init__(self):
        self.calls: list[str] = []

    def complete_json(self, *, stage, system, user, schema, schema_name, case_id=None):
        self.calls.append(stage)
        payload = STAGE_PAYLOADS.get(stage, {})
        if stage == "verification":
            # Echo a SUPPORTED verdict for whatever ids were asked about.
            ids = [line.split("id: ")[1].strip() for line in user.splitlines() if line.startswith("id: ")]
            return {"verdicts": [{"id": i, "verdict": "SUPPORTED", "reason": "ok"} for i in ids]}
        return payload

    def available_cases(self):
        return []


@pytest.fixture(autouse=True)
def stub_client(monkeypatch):
    stub = StubClient()
    monkeypatch.setattr(main, "_client", stub)
    return stub


def new_case() -> str:
    res = client.post(
        "/api/cases",
        json={
            "narrative": NARRATIVE,
            "suspected_drug": "TMP-SMX",
            "adverse_event": "Acute liver injury",
            "age": "34",
            "sex": "F",
        },
    )
    assert res.status_code == 201
    return res.json()["case"]["id"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:59004",
        "https://localhost:3000",
        "http://[::1]:3000",
    ],
)
def test_loopback_origins_allowed(origin):
    res = client.options("/api/cases", headers={"Origin": origin, **PREFLIGHT})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example.com", "http://localhost.attacker.com", "http://127.0.0.1.attacker.com"],
)
def test_non_loopback_origins_rejected(origin):
    res = client.options("/api/cases", headers={"Origin": origin, **PREFLIGHT})
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


def test_health_positions_the_product_correctly():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "not a medical device" in body["disclaimer"]
    assert "reviewer makes every clinically meaningful judgment" in body["disclaimer"]
    assert len(body["who_umc_categories"]) == 6


def test_demo_cases_available():
    cases = client.get("/api/demo-cases").json()
    assert len(cases) >= 3
    assert any(c["is_ambiguous"] for c in cases)


def test_no_endpoint_returns_a_verdict_from_a_narrative():
    """The old one-shot /api/analyze is gone, by design."""
    assert client.post("/api/analyze", json={"narrative": NARRATIVE}).status_code == 404


# ---------------------------------------------------------------------------
# Case lifecycle
# ---------------------------------------------------------------------------


def test_creating_a_case_yields_an_empty_workspace_not_an_assessment():
    body = client.post(
        "/api/cases",
        json={"narrative": NARRATIVE, "suspected_drug": "TMP-SMX", "adverse_event": "Acute liver injury"},
    ).json()
    assert body["case"]["facts"] == []
    assert body["case"]["hypotheses"] == []
    assert body["case"]["conclusion"]["final_assessment"] is None
    # The questionnaire exists but is entirely unanswered.
    assert body["framework"]["total_score"] == 0
    assert body["framework"]["unreviewed_count"] == 10
    assert body["stage"] == "INTAKE"


def test_case_is_listed_and_retrievable():
    case_id = new_case()
    assert any(c["id"] == case_id for c in client.get("/api/cases").json())
    assert client.get(f"/api/cases/{case_id}").json()["case"]["id"] == case_id


def test_unknown_case_is_404():
    assert client.get("/api/cases/case-nope").status_code == 404


def test_case_can_be_deleted():
    case_id = new_case()
    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_intake_validates_required_fields():
    res = client.post("/api/cases", json={"narrative": "", "suspected_drug": "", "adverse_event": ""})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Suggestion runs populate a workspace, not a conclusion
# ---------------------------------------------------------------------------


def test_extraction_produces_unreviewed_suggestions_only():
    case_id = new_case()
    body = client.post(f"/api/cases/{case_id}/suggest/facts").json()
    facts = body["envelope"]["case"]["facts"]
    assert len(facts) == 3
    assert all(f["reviewer_status"] == "AI_SUGGESTED" for f in facts)
    assert all(f["ai"]["value"] for f in facts)
    # Nothing is confirmed, so the case has no usable evidence yet.
    assert body["envelope"]["stats"]["facts_pending"] == 3
    assert body["envelope"]["stats"]["facts_accepted"] == 0


def test_unknown_stage_is_rejected():
    case_id = new_case()
    res = client.post(f"/api/cases/{case_id}/suggest/telepathy")
    assert res.status_code == 400
    assert "Unknown stage" in res.json()["detail"]


def test_rerunning_extraction_preserves_reviewer_decisions():
    case_id = new_case()
    client.post(f"/api/cases/{case_id}/suggest/facts")
    facts = client.get(f"/api/cases/{case_id}").json()["case"]["facts"]
    target = facts[0]["id"]

    client.patch(
        f"/api/cases/{case_id}/review/fact/{target}",
        json={"status": "REVIEWER_MODIFIED", "value": "March 3"},
    )
    client.post(f"/api/cases/{case_id}/suggest/facts")

    after = client.get(f"/api/cases/{case_id}").json()["case"]["facts"]
    kept = next(f for f in after if f["id"] == target)
    assert kept["reviewer_status"] == "REVIEWER_MODIFIED"
    assert kept["reviewer_value"] == "March 3"


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------


def test_accepting_a_fact_makes_it_count():
    case_id = new_case()
    client.post(f"/api/cases/{case_id}/suggest/facts")
    fact_id = client.get(f"/api/cases/{case_id}").json()["case"]["facts"][0]["id"]

    body = client.patch(
        f"/api/cases/{case_id}/review/fact/{fact_id}", json={"status": "REVIEWER_ACCEPTED"}
    ).json()
    assert body["stats"]["facts_accepted"] == 1
    assert body["stats"]["facts_pending"] == 2


def test_naranjo_answer_updates_score_in_the_same_response():
    case_id = new_case()
    body = client.patch(f"/api/cases/{case_id}/review/naranjo/2", json={"value": "YES"}).json()
    assert body["framework"]["total_score"] == 2
    item = next(i for i in body["case"]["naranjo"] if i["number"] == 2)
    assert item["score"] == 2
    assert item["reviewer_answer"] == "YES"


def test_invalid_naranjo_answer_is_rejected():
    case_id = new_case()
    res = client.patch(f"/api/cases/{case_id}/review/naranjo/2", json={"value": "MAYBE"})
    assert res.status_code == 400


def test_unknown_entity_type_is_rejected():
    case_id = new_case()
    res = client.patch(f"/api/cases/{case_id}/review/vibes/x", json={"status": "REVIEWER_ACCEPTED"})
    assert res.status_code == 400
    assert "Unknown entity type" in res.json()["detail"]


def test_bulk_accept_facts():
    case_id = new_case()
    client.post(f"/api/cases/{case_id}/suggest/facts")
    body = client.post(
        f"/api/cases/{case_id}/review/bulk",
        json={"entity_type": "fact", "status": "REVIEWER_ACCEPTED"},
    ).json()
    assert body["stats"]["facts_accepted"] == 3
    assert body["stats"]["facts_pending"] == 0


# ---------------------------------------------------------------------------
# Manual additions
# ---------------------------------------------------------------------------


def test_reviewer_can_add_a_fact_the_ai_missed():
    case_id = new_case()
    body = client.post(
        f"/api/cases/{case_id}/facts", json={"field": "alcohol", "value": "No alcohol use reported"}
    ).json()
    added = body["case"]["facts"][-1]
    assert added["origin"] == "REVIEWER"
    assert added["ai"] is None
    assert added["reviewer_value"] == "No alcohol use reported"


def test_reviewer_can_add_and_remove_timeline_events():
    case_id = new_case()
    body = client.post(
        f"/api/cases/{case_id}/events",
        json={"label": "Liver biopsy", "date_kind": "APPROXIMATE", "display_date": "late March"},
    ).json()
    event = body["case"]["timeline"][-1]
    assert event["timing_uncertain"] is True

    after = client.delete(f"/api/cases/{case_id}/events/{event['id']}").json()
    assert after["case"]["timeline"] == []


def test_adding_an_unknown_fact_field_is_rejected():
    case_id = new_case()
    res = client.post(f"/api/cases/{case_id}/facts", json={"field": "horoscope", "value": "Leo"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Conclusion + audit
# ---------------------------------------------------------------------------


def test_conclusion_and_signoff():
    case_id = new_case()
    body = client.put(
        f"/api/cases/{case_id}/conclusion",
        json={"final_assessment": "Possible", "reviewer_rationale": "My reasoning.", "signed_off": True},
    ).json()
    assert body["case"]["conclusion"]["final_assessment"] == "Possible"
    assert body["case"]["conclusion"]["signed_off"] is True
    assert body["stage"] == "REPORT"


def test_audit_trail_records_ai_and_reviewer_separately():
    case_id = new_case()
    client.post(f"/api/cases/{case_id}/suggest/facts")
    fact_id = client.get(f"/api/cases/{case_id}").json()["case"]["facts"][0]["id"]
    client.patch(f"/api/cases/{case_id}/review/fact/{fact_id}", json={"status": "REVIEWER_REJECTED"})

    entries = client.get(f"/api/cases/{case_id}/audit").json()
    actors = {e["actor"] for e in entries}
    assert actors == {"AI", "REVIEWER"}
    assert any(e["action"] == "SUGGEST_FACTS" and e["actor"] == "AI" for e in entries)
    assert any(e["action"] == "REVIEW" and e["actor"] == "REVIEWER" for e in entries)


def test_rationale_draft_is_built_from_confirmed_evidence(stub_client):
    case_id = new_case()
    client.post(f"/api/cases/{case_id}/suggest/facts")
    client.post(f"/api/cases/{case_id}/review/bulk", json={"entity_type": "fact", "status": "REVIEWER_ACCEPTED"})
    body = client.post(f"/api/cases/{case_id}/suggest/rationale").json()

    assert body["envelope"]["case"]["conclusion"]["ai_draft_rationale"]
    assert body["envelope"]["case"]["conclusion"]["rationale_status"] == "AI_SUGGESTED"
    assert "rationale" in stub_client.calls
