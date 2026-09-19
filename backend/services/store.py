"""SQLite persistence for cases and the audit trail.

Two tables, deliberately:

  cases   one row per case, holding the whole CaseDocument as JSON. Pydantic
          stays the single source of truth for shape, so there is no schema to
          migrate every time a screen gains a field -- which matters when the
          document model is still moving.
  audit   append-only. Never updated, never deleted. This is the record that
          lets a reviewer answer "what did the AI propose and what did I do
          about it", so it must not be rewritable through the app.

A connection is opened per operation rather than shared. FastAPI runs sync
handlers in a worker threadpool, and a module-level SQLite connection across
threads is a well-known source of intermittent corruption. At this scale the
open cost is irrelevant.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Iterable, Optional

from schemas.review import (
    AuditEntry,
    CaseDocument,
    CaseStage,
    CaseSummary,
    Origin,
    utcnow,
)

DEFAULT_DB = Path(__file__).resolve().parent.parent / "causaltrace.db"


def db_path() -> Path:
    """Read from the environment each call so tests can point at a temp file."""
    return Path(os.environ.get("CAUSALTRACE_DB", str(DEFAULT_DB)))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL keeps a long reviewer session from blocking on a concurrent write.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    doc         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    summary     TEXT NOT NULL DEFAULT '',
    before_json TEXT,
    after_json  TEXT
);

CREATE INDEX IF NOT EXISTS audit_case_idx ON audit(case_id, id);
CREATE INDEX IF NOT EXISTS cases_updated_idx ON cases(updated_at DESC);
"""


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def new_case_id() -> str:
    return f"case-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def save_case(doc: CaseDocument) -> CaseDocument:
    doc.updated_at = utcnow()
    payload = doc.model_dump_json()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO cases (id, created_at, updated_at, doc) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, doc=excluded.doc",
            (doc.id, doc.created_at, doc.updated_at, payload),
        )
    return doc


def get_case(case_id: str) -> Optional[CaseDocument]:
    with _connect() as conn:
        row = conn.execute("SELECT doc FROM cases WHERE id = ?", (case_id,)).fetchone()
    return CaseDocument.model_validate_json(row["doc"]) if row else None


def delete_case(case_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    return cur.rowcount > 0


def stage_of(doc: CaseDocument) -> CaseStage:
    """Furthest point the case has actually reached.

    Derived from content rather than stored, so it cannot drift out of sync
    with the document after an edit.
    """
    if doc.conclusion.signed_off:
        return CaseStage.REPORT
    if doc.conclusion.final_assessment:
        return CaseStage.CONCLUSION
    if doc.who_umc is not None:
        return CaseStage.WHO_UMC
    # A blank questionnaire is seeded at intake, so its mere presence means
    # nothing. The Naranjo stage is reached only once it has been suggested or
    # answered.
    if any(i.ai_answer is not None or i.reviewer_status.value.startswith("REVIEWER") for i in doc.naranjo):
        return CaseStage.NARANJO
    if doc.missing_evidence:
        return CaseStage.MISSING
    if doc.hypotheses:
        return CaseStage.HYPOTHESES
    if doc.dimensions:
        return CaseStage.INVESTIGATION
    if doc.timeline:
        return CaseStage.TIMELINE
    if doc.facts:
        return CaseStage.EVIDENCE
    return CaseStage.INTAKE


def list_cases() -> list[CaseSummary]:
    with _connect() as conn:
        rows = conn.execute("SELECT doc FROM cases ORDER BY updated_at DESC").fetchall()
    out: list[CaseSummary] = []
    for row in rows:
        doc = CaseDocument.model_validate_json(row["doc"])
        out.append(
            CaseSummary(
                id=doc.id,
                title=doc.title or f"{doc.suspected_drug} / {doc.adverse_event}",
                suspected_drug=doc.suspected_drug,
                adverse_event=doc.adverse_event,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                stage=stage_of(doc),
                final_assessment=doc.conclusion.final_assessment,
                signed_off=doc.conclusion.signed_off,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def log(
    case_id: str,
    *,
    actor: Origin,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    summary: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit (case_id, at, actor, action, entity_type, entity_id, summary,"
            " before_json, after_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                utcnow(),
                actor.value,
                action,
                entity_type,
                entity_id,
                summary,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
            ),
        )


def log_many(case_id: str, entries: Iterable[dict]) -> None:
    for entry in entries:
        log(case_id, **entry)


def get_audit(case_id: str) -> list[AuditEntry]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    return [
        AuditEntry(
            id=row["id"],
            at=row["at"],
            actor=Origin(row["actor"]),
            action=row["action"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            summary=row["summary"],
            before=json.loads(row["before_json"]) if row["before_json"] else None,
            after=json.loads(row["after_json"]) if row["after_json"] else None,
        )
        for row in rows
    ]
