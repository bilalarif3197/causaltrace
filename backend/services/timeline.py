"""Stage 2 -- timeline reconstruction.

Turns extracted facts into a normalised chronological sequence.

The hard requirement: when the narrative gives only relative timing ("two weeks
later", "three days after initiation"), we preserve the *ordering* and keep the
original phrase, and we do not invent a calendar date. A fabricated date would
be an especially damaging hallucination here, because temporal sequence is the
single heaviest-weighted element of Naranjo (item 2, +2/-1).
"""

from __future__ import annotations

from typing import Any

from schemas.models import DateCertainty, EventCategory, TimelineEvent
from services.spans import locate_span

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short clinical label, e.g. 'Drug A started'."},
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in EventCategory],
                    },
                    "order": {
                        "type": "integer",
                        "description": "1-based chronological rank. Ties allowed for simultaneous events.",
                    },
                    "date": {
                        "type": ["string", "null"],
                        "description": (
                            "Full ISO-8601 date ONLY if the narrative states a complete date "
                            "including the year. If the year is not stated, leave this null and "
                            "put the day/month in display_date. Never infer a year."
                        ),
                    },
                    "display_date": {
                        "type": ["string", "null"],
                        "description": "Human label: 'Jan 03', 'Day 14', or null.",
                    },
                    "relative_text": {
                        "type": ["string", "null"],
                        "description": "The relative phrase used, e.g. 'two weeks later'.",
                    },
                    "date_certainty": {"type": "string", "enum": ["EXACT", "RELATIVE", "UNKNOWN"]},
                    "actor": {"type": ["string", "null"], "description": "Drug or entity involved."},
                    "evidence_text": {"type": ["string", "null"], "description": "Verbatim supporting quote."},
                },
            },
        }
    },
}

SYSTEM = """You reconstruct a clinical timeline from an adverse drug event case narrative.

Absolute rules:
- NEVER invent a calendar date, and never infer a year that is not written down. Set
  `date` only when the narrative states a complete date including the year. A narrative
  saying "3 January" with no year is date_certainty EXACT with date null and
  display_date "Jan 03" -- the day is stated, the year is not.
- If timing is relative, set date to null, date_certainty to RELATIVE, and put the
  original phrase in relative_text.
- Relative ordering always matters more than dates. Always populate `order` correctly,
  even when every date is unknown.
- Include drug starts, drug stops, dose changes, event onset, key labs, infections,
  rechallenge and recovery.
- `evidence_text` must be copied verbatim from the narrative.
- Do not add events that are not described in the text."""


def build(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None) -> list[TimelineEvent]:
    user = (
        f"Suspected drug: {suspected_drug}\n"
        f"Adverse event: {adverse_event}\n\n"
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        "Reconstruct the chronological timeline."
    )
    raw = client.complete_json(
        stage="timeline",
        system=SYSTEM,
        user=user,
        schema=SCHEMA,
        schema_name="timeline",
        case_id=case_id,
    )

    events: list[TimelineEvent] = []
    for i, row in enumerate(raw.get("events", [])):
        span = locate_span(narrative, row.get("evidence_text"))
        certainty = DateCertainty(row.get("date_certainty") or "UNKNOWN")
        date = row.get("date")

        # Guard against a date attached to non-exact timing (an inferred date),
        # and against EXACT asserted with nothing to show for it. EXACT with a
        # display_date but no ISO date is legitimate: the narrative stated a
        # day and month but never a year, and inventing one would be a
        # fabrication.
        if date and certainty is not DateCertainty.EXACT:
            date = None
        if certainty is DateCertainty.EXACT and not date and not row.get("display_date"):
            certainty = DateCertainty.UNKNOWN

        events.append(
            TimelineEvent(
                id=f"t{i:03d}",
                label=row.get("label", ""),
                category=EventCategory(row.get("category") or "OTHER"),
                order=int(row.get("order") or i + 1),
                date=date,
                display_date=row.get("display_date"),
                relative_text=row.get("relative_text"),
                date_certainty=certainty,
                actor=row.get("actor"),
                span=span,
            )
        )

    # Stable sort on the model's ordering; ties keep emission order.
    events.sort(key=lambda e: e.order)
    for i, e in enumerate(events, start=1):
        e.order = i
    return events
