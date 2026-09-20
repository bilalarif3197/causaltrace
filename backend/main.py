"""CausalTrace API — an AI-assisted pharmacovigilance review workspace.

Note what is deliberately absent: there is no endpoint that takes a narrative
and returns a causality verdict. Suggestion runs populate a review workspace;
the assessment emerges from reviewer decisions recorded through
`/review/...` and `/conclusion`.

Research prototype. Not a medical device and not a clinical decision tool.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from schemas.review import (  # noqa: E402
    AuditEntry,
    CaseEnvelope,
    CaseSummary,
    PatientContext,
    ReviewerStatus,
    WHO_UMC_CATEGORIES,
)
from services import cases as demo_cases  # noqa: E402
from services import store, workspace  # noqa: E402
from services.llm_client import MockUnavailable, build_client  # noqa: E402
from services.workspace import DISCLAIMER, WorkspaceError  # noqa: E402

app = FastAPI(
    title="CausalTrace API",
    version="0.2.0",
    description=DISCLAIMER,
)

# Any loopback origin, on any port: the dev server, a browser preview proxy and
# an SSH tunnel all present different origins for the same machine, and
# browsers treat localhost and 127.0.0.1 as distinct regardless.
LOOPBACK_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o],
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", LOOPBACK_ORIGIN_REGEX),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_client = build_client()
store.init_db()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateCaseBody(BaseModel):
    narrative: str = Field(min_length=1)
    suspected_drug: str = Field(min_length=1)
    adverse_event: str = Field(min_length=1)
    title: str = ""
    indication: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    concomitant_medications: Optional[str] = None
    comorbidities: Optional[str] = None
    demo_case_id: Optional[str] = None


class ReviewBody(BaseModel):
    status: Optional[ReviewerStatus] = None
    value: Optional[str] = None
    note: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BulkReviewBody(BaseModel):
    entity_type: str
    status: ReviewerStatus
    section: Optional[str] = None


class AddFactBody(BaseModel):
    field: str
    value: str = Field(min_length=1)
    note: Optional[str] = None


class AddEventBody(BaseModel):
    label: str = Field(min_length=1)
    order_index: Optional[int] = None
    date_kind: str = "UNKNOWN"
    display_date: Optional[str] = None
    relative_text: Optional[str] = None
    category: str = "OTHER"
    actor: Optional[str] = None


class AddHypothesisBody(BaseModel):
    label: str = Field(min_length=1)
    kind: str = "OTHER"


class AddMissingBody(BaseModel):
    prompt: str = Field(min_length=1)
    why_it_matters: str = ""


class ConclusionBody(BaseModel):
    final_assessment: Optional[str] = None
    primary_cause_hypothesis_id: Optional[str] = None
    reviewer_rationale: Optional[str] = None
    signed_off: Optional[bool] = None


class SuggestResponse(BaseModel):
    envelope: CaseEnvelope
    note: str
    stage: str


class BatchBody(BaseModel):
    #: Defaults to every parallel-safe stage, which is what first open wants.
    stages: Optional[list[str]] = None


class BatchResponse(BaseModel):
    envelope: CaseEnvelope
    notes: list[str]
    stages: list[str]
    #: Per-stage failures. A partial batch still returns 200 with what worked.
    failed: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(case_id: str):
    doc = store.get_case(case_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No case '{case_id}'.")
    return doc


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": _client.mode,
        "model": _client.name,
        "disclaimer": DISCLAIMER,
        "json_mode": getattr(_client, "active_json_mode", None),
        "notes": getattr(_client, "notes", []),
        "mock_cases": getattr(_client, "available_cases", list)(),
        "who_umc_categories": WHO_UMC_CATEGORIES,
    }


@app.get("/api/demo-cases")
def list_demo_cases() -> list[dict]:
    return [
        {
            "case_id": case.case_id,
            "title": case.title,
            "description": case.description,
            "narrative": case.narrative,
            "suspected_drug": case.suspected_drug,
            "adverse_event": case.adverse_event,
            "is_ambiguous": case.is_ambiguous,
            "indication": case.indication,
            "age": case.age,
            "sex": case.sex,
            "concomitant_medications": case.concomitant_medications,
            "comorbidities": case.comorbidities,
        }
        for case in demo_cases.EXAMPLE_CASES
    ]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@app.get("/api/cases", response_model=list[CaseSummary])
def list_cases() -> list[CaseSummary]:
    return store.list_cases()


@app.post("/api/cases", response_model=CaseEnvelope, status_code=201)
def create_case(body: CreateCaseBody) -> CaseEnvelope:
    doc = workspace.create_case(
        narrative=body.narrative,
        suspected_drug=body.suspected_drug,
        adverse_event=body.adverse_event,
        title=body.title,
        patient=PatientContext(
            indication=body.indication,
            age=body.age,
            sex=body.sex,
            concomitant_medications=body.concomitant_medications,
            comorbidities=body.comorbidities,
        ),
        demo_case_id=body.demo_case_id,
        client=_client,
    )
    return workspace.envelope(doc)


@app.get("/api/cases/{case_id}", response_model=CaseEnvelope)
def get_case(case_id: str) -> CaseEnvelope:
    return workspace.envelope(_load(case_id))


@app.delete("/api/cases/{case_id}", status_code=204, response_model=None)
def delete_case(case_id: str) -> Response:
    if not store.delete_case(case_id):
        raise HTTPException(status_code=404, detail=f"No case '{case_id}'.")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# AI suggestion runs -- always explicit, never automatic
# ---------------------------------------------------------------------------


@app.post("/api/cases/{case_id}/suggest-batch", response_model=BatchResponse)
def run_suggest_batch(case_id: str, body: BatchBody) -> BatchResponse:
    """Run the narrative-only stages concurrently.

    One request rather than several, because each single-stage call rewrites
    the whole document: firing them in parallel from the browser would make
    the last response win and silently discard the rest.
    """
    doc = _load(case_id)
    stages = body.stages or list(workspace.PARALLEL_STAGES)
    try:
        doc, notes, failed = workspace.run_suggest_batch(_client, doc, stages)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchResponse(
        envelope=workspace.envelope(doc),
        notes=notes,
        stages=[s for s in stages if s not in failed],
        failed=failed,
    )


@app.post("/api/cases/{case_id}/suggest/{stage}", response_model=SuggestResponse)
def run_suggest(case_id: str, stage: str) -> SuggestResponse:
    doc = _load(case_id)
    try:
        doc, note = workspace.run_suggest(_client, doc, stage)
    except MockUnavailable as exc:
        # Valid request; the server simply has no recorded output and no key.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuggestResponse(envelope=workspace.envelope(doc), note=note, stage=stage)


# ---------------------------------------------------------------------------
# Reviewer decisions
# ---------------------------------------------------------------------------


@app.patch("/api/cases/{case_id}/review/{entity_type}/{entity_id}", response_model=CaseEnvelope)
def review_entity(case_id: str, entity_type: str, entity_id: str, body: ReviewBody) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc = workspace.apply_review(
            doc,
            entity_type,
            entity_id,
            status=body.status,
            value=body.value,
            note=body.note,
            extra=body.extra,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace.envelope(doc)


@app.post("/api/cases/{case_id}/review/bulk", response_model=CaseEnvelope)
def bulk_review(case_id: str, body: BulkReviewBody) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc, _ = workspace.bulk_review(doc, body.entity_type, body.status, body.section)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace.envelope(doc)


# ---------------------------------------------------------------------------
# Manual additions
# ---------------------------------------------------------------------------


@app.post("/api/cases/{case_id}/facts", response_model=CaseEnvelope, status_code=201)
def add_fact(case_id: str, body: AddFactBody) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc, _ = workspace.add_fact(doc, field=body.field, value=body.value, note=body.note)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace.envelope(doc)


@app.post("/api/cases/{case_id}/events", response_model=CaseEnvelope, status_code=201)
def add_event(case_id: str, body: AddEventBody) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc, _ = workspace.add_event(
            doc,
            label=body.label,
            order_index=body.order_index,
            date_kind=body.date_kind,
            display_date=body.display_date,
            relative_text=body.relative_text,
            category=body.category,
            actor=body.actor,
        )
    except (WorkspaceError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace.envelope(doc)


@app.delete("/api/cases/{case_id}/events/{event_id}", response_model=CaseEnvelope)
def delete_event(case_id: str, event_id: str) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc = workspace.delete_event(doc, event_id)
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return workspace.envelope(doc)


@app.post("/api/cases/{case_id}/hypotheses", response_model=CaseEnvelope, status_code=201)
def add_hypothesis(case_id: str, body: AddHypothesisBody) -> CaseEnvelope:
    doc = _load(case_id)
    doc, _ = workspace.add_hypothesis(doc, label=body.label, kind=body.kind)
    return workspace.envelope(doc)


@app.post("/api/cases/{case_id}/missing", response_model=CaseEnvelope, status_code=201)
def add_missing(case_id: str, body: AddMissingBody) -> CaseEnvelope:
    doc = _load(case_id)
    doc, _ = workspace.add_missing_item(doc, prompt=body.prompt, why=body.why_it_matters)
    return workspace.envelope(doc)


# ---------------------------------------------------------------------------
# Conclusion + audit
# ---------------------------------------------------------------------------


@app.put("/api/cases/{case_id}/conclusion", response_model=CaseEnvelope)
def set_conclusion(case_id: str, body: ConclusionBody) -> CaseEnvelope:
    doc = _load(case_id)
    try:
        doc = workspace.set_conclusion(
            doc,
            final_assessment=body.final_assessment,
            primary_cause_hypothesis_id=body.primary_cause_hypothesis_id,
            reviewer_rationale=body.reviewer_rationale,
            signed_off=body.signed_off,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace.envelope(doc)


@app.get("/api/cases/{case_id}/audit", response_model=list[AuditEntry])
def get_audit(case_id: str) -> list[AuditEntry]:
    _load(case_id)
    return store.get_audit(case_id)
