"""Stage 3 -- competing causal hypotheses.

The product thesis lives here. A temporal relationship is not causality, so
instead of collapsing a case into one verdict we enumerate the plausible
explanations and sort the evidence for each into supports / contradicts /
unknown.

Deliberately absent: numeric probabilities. "Drug A is 83% likely to be
responsible" is not a quantity this evidence can produce, so the schema cannot
express it. Strength is a qualitative label that must be justified from the
evidence counts, and `insufficient_to_distinguish` lets the system say the
honest thing when two hypotheses genuinely cannot be separated.
"""

from __future__ import annotations

from typing import Any

from schemas.models import EvidenceItem, Hypothesis, HypothesisKind, SupportLabel
from services.spans import locate_span

_EVIDENCE_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "statement": {"type": "string", "description": "The evidential point, in one sentence."},
            "evidence_text": {
                "type": ["string", "null"],
                "description": "Verbatim quote, or null when the point is that something is NOT reported.",
            },
        },
    },
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis": {"type": "string", "description": "e.g. 'Drug A caused the liver injury'."},
                    "kind": {"type": "string", "enum": [k.value for k in HypothesisKind]},
                    "supporting_evidence": _EVIDENCE_ARRAY,
                    "contradicting_evidence": _EVIDENCE_ARRAY,
                    "unknown_evidence": _EVIDENCE_ARRAY,
                    "support_label": {
                        "type": "string",
                        "enum": [s.value for s in SupportLabel],
                    },
                    "label_rationale": {
                        "type": "string",
                        "description": "Why this label, referring to the evidence above.",
                    },
                },
            },
        },
        "insufficient_to_distinguish": {
            "type": "boolean",
            "description": "True if the evidence cannot separate the leading hypotheses.",
        },
        "distinguishing_note": {
            "type": "string",
            "description": "What additional information would separate them.",
        },
    },
}

SYSTEM = """You enumerate competing causal explanations for an adverse event in a case narrative.

Always consider, and include where the narrative supports them:
- the suspected drug
- each significant concomitant medication
- any documented infection
- the underlying disease
- a drug-drug interaction, where plausible
- an explicit "insufficient evidence" hypothesis when the case cannot be resolved

For each hypothesis sort the evidence into three buckets:
- supporting_evidence: facts that make this cause more likely
- contradicting_evidence: facts that argue against it (e.g. the drug continued while the
  patient recovered)
- unknown_evidence: decisive information the narrative does not provide (no rechallenge,
  no drug levels, no serology)

Absolute rules:
- NEVER output a numeric probability, percentage or likelihood. Strength is one of the
  four allowed qualitative labels only.
- Use "Insufficient evidence" freely. Two hypotheses being indistinguishable is a valid
  and valuable finding, not a failure.
- Every supporting or contradicting point needs a verbatim quote. Points in
  unknown_evidence describe what is absent, so they carry evidence_text null.
- Do not let the suspected drug win by default. Apply the same scrutiny to every
  candidate."""


def _items(rows: list[dict], narrative: str, prefix: str) -> list[EvidenceItem]:
    out: list[EvidenceItem] = []
    for i, row in enumerate(rows or []):
        quote = row.get("evidence_text")
        out.append(
            EvidenceItem(
                id=f"{prefix}{i:02d}",
                statement=row.get("statement", ""),
                evidence_text=quote,
                span=locate_span(narrative, quote),
            )
        )
    return out


def generate(
    client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None
) -> tuple[list[Hypothesis], bool, str]:
    user = (
        f"Suspected drug: {suspected_drug}\n"
        f"Adverse event: {adverse_event}\n\n"
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        "Enumerate every plausible competing causal explanation."
    )
    raw = client.complete_json(
        stage="hypotheses",
        system=SYSTEM,
        user=user,
        schema=SCHEMA,
        schema_name="competing_hypotheses",
        case_id=case_id,
    )

    hypotheses: list[Hypothesis] = []
    for i, row in enumerate(raw.get("hypotheses", [])):
        hid = f"h{i:02d}"
        supporting = _items(row.get("supporting_evidence", []), narrative, f"{hid}s")
        contradicting = _items(row.get("contradicting_evidence", []), narrative, f"{hid}c")
        unknown = _items(row.get("unknown_evidence", []), narrative, f"{hid}u")

        label = SupportLabel(row.get("support_label") or SupportLabel.INSUFFICIENT.value)
        # A strength label is only meaningful if grounded support actually
        # exists. Without a single locatable supporting quote, force the label
        # down regardless of what the model asserted.
        grounded = [e for e in supporting if e.span and e.span.located]
        if not grounded and label is not SupportLabel.INSUFFICIENT:
            label = SupportLabel.INSUFFICIENT

        hypotheses.append(
            Hypothesis(
                id=hid,
                hypothesis=row.get("hypothesis", ""),
                kind=HypothesisKind(row.get("kind") or "CONCOMITANT_DRUG"),
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                unknown_evidence=unknown,
                support_label=label,
                label_rationale=row.get("label_rationale", ""),
            )
        )

    return (
        hypotheses,
        bool(raw.get("insufficient_to_distinguish", False)),
        raw.get("distinguishing_note", "") or "",
    )
