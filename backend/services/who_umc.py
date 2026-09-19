"""WHO-UMC causality assessment (optional second framework).

Unlike Naranjo, WHO-UMC is explicitly *not* an arithmetic instrument. It is a
category judgement weighing clinical plausibility, and pretending to reduce it
to a formula would misrepresent the method. So this module asks the model for a
category plus its reasoning against the published criteria, and surfaces the
major uncertainty alongside it.

The UI keeps this visually separate from Naranjo for exactly that reason: one
is a reproducible score, the other is a structured judgement, and conflating
them would be misleading.
"""

from __future__ import annotations

from typing import Any

from schemas.models import Answer, EvidenceItem, WhoUmcCriterion, WhoUmcResult
from services.spans import locate_span

CATEGORIES = [
    "Certain",
    "Probable",
    "Possible",
    "Unlikely",
    "Conditional/Unclassified",
    "Unassessable/Unclassifiable",
]

CRITERIA = [
    "Plausible temporal relationship to drug intake",
    "Cannot be explained by disease or other drugs",
    "Response to withdrawal plausible (dechallenge)",
    "Event definitive pharmacologically or phenomenologically",
    "Rechallenge satisfactory, if performed",
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": CATEGORIES},
        "reasoning": {"type": "string"},
        "major_uncertainty": {
            "type": "string",
            "description": "The single biggest thing that could overturn this classification.",
        },
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "enum": CRITERIA},
                    "met": {"type": "string", "enum": ["YES", "NO", "UNKNOWN"]},
                    "note": {"type": "string"},
                },
            },
        },
        "supporting_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "evidence_text": {"type": ["string", "null"]},
                },
            },
        },
    },
}

SYSTEM = """You apply the WHO-UMC causality assessment system to a case narrative.

Categories: Certain, Probable, Possible, Unlikely, Conditional/Unclassified,
Unassessable/Unclassifiable.

Guidance:
- "Certain" requires a rechallenge or otherwise definitive evidence. It is rare.
- Use "Conditional/Unclassified" when more data are needed, and
  "Unassessable/Unclassifiable" when the report is too incomplete to judge.
- A documented alternative explanation normally caps the assessment at "Possible".
- WHO-UMC is a judgement, not a formula. Explain your reasoning against the criteria,
  and state the single biggest uncertainty plainly.
- Quote the narrative verbatim for each supporting point."""


def assess(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None) -> WhoUmcResult:
    user = (
        f"Suspected drug: {suspected_drug}\n"
        f"Adverse event: {adverse_event}\n\n"
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        f"Assess causality using WHO-UMC, addressing each criterion:\n"
        + "\n".join(f"- {c}" for c in CRITERIA)
    )
    raw = client.complete_json(
        stage="who_umc",
        system=SYSTEM,
        user=user,
        schema=SCHEMA,
        schema_name="who_umc",
        case_id=case_id,
    )

    evidence = [
        EvidenceItem(
            id=f"w{i:02d}",
            statement=row.get("statement", ""),
            evidence_text=row.get("evidence_text"),
            span=locate_span(narrative, row.get("evidence_text")),
        )
        for i, row in enumerate(raw.get("supporting_evidence", []))
    ]

    criteria = [
        WhoUmcCriterion(
            criterion=row.get("criterion", ""),
            met=Answer(row.get("met") or "UNKNOWN"),
            note=row.get("note", ""),
        )
        for row in raw.get("criteria", [])
    ]

    classification = raw.get("classification") or "Unassessable/Unclassifiable"
    if classification not in CATEGORIES:
        classification = "Unassessable/Unclassifiable"

    return WhoUmcResult(
        classification=classification,  # type: ignore[arg-type]
        reasoning=raw.get("reasoning", ""),
        criteria=criteria,
        supporting_evidence=evidence,
        major_uncertainty=raw.get("major_uncertainty", ""),
    )
