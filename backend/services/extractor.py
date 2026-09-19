"""Stage 1 -- structured evidence extraction.

Pulls a fixed set of clinical slots out of the narrative. Every extracted fact
must carry a verbatim quote; quotes are then resolved to character offsets by
`spans.locate_span`, and anything unlocatable is demoted to UNKNOWN before it
can reach the user or the scorer.

This module makes no causal judgement whatsoever. It reports what the text
says. Causal reasoning happens in `hypotheses.py` and `naranjo.py`, and keeping
the two apart is what makes the evidence trail auditable.
"""

from __future__ import annotations

from typing import Any

from schemas.models import Claim, ClaimStatus
from services.spans import locate_span

#: The slots we always attempt. Reporting a slot as UNKNOWN is a real result --
#: a fixed slate means "not reported" is visible rather than silently omitted.
SLOTS: list[tuple[str, str]] = [
    ("suspected_drug", "The drug suspected of causing the event, with dose and route if stated."),
    ("concomitant_drugs", "Every other drug the patient was taking, each as its own claim."),
    ("drug_timing", "When each drug was started or stopped, absolute or relative."),
    ("doses", "Doses and any dose changes."),
    ("adverse_event", "The adverse event itself, as described."),
    ("event_onset", "When the adverse event began, absolute or relative to drug start."),
    ("diagnoses_comorbidities", "Underlying diagnoses and comorbidities."),
    ("infections", "Any documented infection, including timing."),
    ("labs", "Relevant laboratory values, with numbers and timing where given."),
    ("diagnostic_tests", "Imaging, biopsy, serology and other diagnostic workup."),
    ("treatment_withdrawal", "Whether and when the suspected drug was withdrawn."),
    ("dechallenge_outcome", "What happened after withdrawal (Naranjo item 3)."),
    ("rechallenge", "Any readministration and its outcome (Naranjo item 4)."),
    ("previous_exposure", "Prior exposure or prior similar reaction (Naranjo item 9)."),
    ("dose_response", "Any relationship between dose change and severity (Naranjo item 8)."),
    ("drug_levels", "Measured drug concentrations (Naranjo item 7)."),
    ("alternative_causes", "Competing explanations: other drugs, infection, disease (Naranjo item 5)."),
    ("objective_evidence", "Objective confirmation of the event (Naranjo item 10)."),
    ("prior_knowledge", "Prior literature or known label associations cited in the case (Naranjo item 1)."),
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "enum": [name for name, _ in SLOTS]},
                    "claim": {"type": "string", "description": "What this fact asserts, in one sentence."},
                    "value": {"type": ["string", "null"], "description": "The specific value, or null if not reported."},
                    "evidence_text": {
                        "type": ["string", "null"],
                        "description": "Verbatim span copied from the narrative, or null if not reported.",
                    },
                    "confidence": {"type": "number", "description": "0.0-1.0 confidence in this extraction."},
                    "status": {"type": "string", "enum": ["SUPPORTED", "UNKNOWN"]},
                },
            },
        }
    },
}

SYSTEM = """You extract structured clinical facts from a published adverse drug event case narrative.

You are an extractor, not a judge. Do not assess causality, do not score anything, and do
not infer beyond the text.

Absolute rules:
- `evidence_text` must be copied character-for-character from the narrative. Never
  paraphrase, reformat, correct, or summarise a quote.
- If the narrative does not report a slot, emit one claim for it with value null,
  evidence_text null, and status UNKNOWN. "Not reported" is a real, useful finding.
- Never infer a fact that is not stated. Do not fill gaps with clinical knowledge of what
  is typical for the drug or the condition.
- Emit a separate claim per concomitant drug, per infection, and per lab abnormality
  rather than bundling them into one.
- status is SUPPORTED only when you have a genuine verbatim quote.
- The `claim` text must state a FACT, never an interpretation. The slot already carries
  the interpretation, so do not restate it in the claim.
    Wrong: "Pneumonia is a potential alternative cause."   (the narrative never says this)
    Right: "Pneumonia was documented on chest radiograph." (slot: alternative_causes)
  An independent auditor checks each claim against its quote and rejects any claim
  asserting more than the quote literally says -- including causal framing you added."""


def extract(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None) -> list[Claim]:
    slot_block = "\n".join(f"- {name}: {desc}" for name, desc in SLOTS)
    user = (
        f"Suspected drug: {suspected_drug}\n"
        f"Adverse event: {adverse_event}\n\n"
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        f"Extract claims for every one of these slots:\n{slot_block}"
    )

    raw = client.complete_json(
        stage="extraction",
        system=SYSTEM,
        user=user,
        schema=SCHEMA,
        schema_name="evidence_extraction",
        case_id=case_id,
    )

    claims: list[Claim] = []
    for i, row in enumerate(raw.get("claims", [])):
        quote = row.get("evidence_text")
        span = locate_span(narrative, quote)
        status = ClaimStatus(row.get("status", "UNKNOWN"))

        claim = Claim(
            id=f"c{i:03d}",
            slot=row.get("slot", "other"),
            claim=row.get("claim", ""),
            value=row.get("value"),
            evidence_text=quote,
            confidence=float(row.get("confidence") or 0.0),
            status=status,
            span=span,
        )

        # Deterministic grounding gate: a SUPPORTED claim whose quote is not
        # actually in the narrative is a fabricated citation. Demote it here,
        # before it reaches verification, the UI, or the scorer.
        if claim.status is ClaimStatus.SUPPORTED and (span is None or not span.located):
            claim.status = ClaimStatus.UNKNOWN
            claim.dropped = True
            claim.drop_reason = "Cited quote could not be located in the narrative."
            claim.value = None

        claims.append(claim)

    return claims


def covered_slots(claims: list[Claim]) -> dict[str, bool]:
    """Which slots ended up with at least one grounded claim."""
    supported = {c.slot for c in claims if c.status is ClaimStatus.SUPPORTED}
    return {name: name in supported for name, _ in SLOTS}
