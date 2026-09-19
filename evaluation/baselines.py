"""Baseline systems to compare CausalTrace against.

Baseline A -- single-pass verdict
    One call: "did this drug cause this event?" The model returns a causality
    category directly. This is what most people actually build, and it has no
    evidence trail at all.

Baseline B -- single-pass Naranjo questionnaire
    One call: fill in the whole Naranjo scale AND report the total. This is the
    more interesting comparison, because it isolates exactly one variable --
    who does the arithmetic and the grounding. Same scale, same case, but the
    model self-reports the total instead of the total being computed from
    independently grounded item answers.

Both baselines go through the same `ModelClient`, so mock mode can replay them
alongside the CausalTrace stages.

`self_reported_total` is kept separate from the recomputed total on purpose: the
gap between "what the model said the score was" and "what its own answers
actually sum to" is a metric worth reporting.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from services.naranjo import ITEMS_BY_NUMBER, NARANJO_ITEMS, classify  # noqa: E402

CATEGORIES = ["Definite", "Probable", "Possible", "Doubtful"]

# --------------------------------------------------------------------------
# Baseline A
# --------------------------------------------------------------------------

A_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "explanation": {"type": "string"},
    },
}

A_SYSTEM = (
    "You are a clinician assessing whether a drug caused an adverse event. "
    "Read the case and classify causality as Definite, Probable, Possible or Doubtful."
)


def baseline_a(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None) -> dict:
    raw = client.complete_json(
        stage="baseline_a",
        system=A_SYSTEM,
        user=(
            f"Suspected drug: {suspected_drug}\nAdverse event: {adverse_event}\n\n"
            f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\nClassify the causality."
        ),
        schema=A_SCHEMA,
        schema_name="baseline_a",
        case_id=case_id,
    )
    return {
        "system": "baseline_a",
        "category": raw.get("category"),
        "score": None,  # produces no score at all
        "self_reported_total": None,
        "items": {},
        "explanation": raw.get("explanation", ""),
        "grounded_items": 0,
    }


# --------------------------------------------------------------------------
# Baseline B
# --------------------------------------------------------------------------

B_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "answer": {"type": "string", "enum": ["YES", "NO", "UNKNOWN"]},
                },
            },
        },
        "total_score": {"type": "integer", "description": "The total Naranjo score."},
        "category": {"type": "string", "enum": CATEGORIES},
    },
}

B_SYSTEM = (
    "You are a clinician applying the Naranjo ADR Probability Scale. Answer all 10 items, "
    "add up the score using the standard weights, and give the final classification."
)


def baseline_b(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None) -> dict:
    questions = "\n".join(f"{s.number}. {s.question}" for s in NARANJO_ITEMS)
    raw = client.complete_json(
        stage="baseline_b",
        system=B_SYSTEM,
        user=(
            f"Suspected drug: {suspected_drug}\nAdverse event: {adverse_event}\n\n"
            f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
            f"Naranjo items:\n{questions}\n\nAnswer all items, total the score, and classify."
        ),
        schema=B_SCHEMA,
        schema_name="baseline_b",
        case_id=case_id,
    )

    answers = {int(r["number"]): r["answer"] for r in raw.get("items", [])}

    # Recompute from the model's own answers using the published weights. Where
    # this disagrees with `total_score`, the model mis-added its own worksheet.
    recomputed = 0
    for number, answer in answers.items():
        spec = ITEMS_BY_NUMBER.get(number)
        if spec:
            from schemas.models import Answer

            recomputed += spec.weight(Answer(answer))

    return {
        "system": "baseline_b",
        "category": raw.get("category"),
        "score": recomputed,
        "self_reported_total": raw.get("total_score"),
        "recomputed_matches_self_report": raw.get("total_score") == recomputed,
        "recomputed_category": classify(recomputed),
        "items": answers,
        "explanation": "",
        # Baseline B cites nothing, so no item is evidence-grounded.
        "grounded_items": 0,
    }
