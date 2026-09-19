"""Stage 4 -- evidence verification.

A second, independent pass that re-reads the narrative and asks one narrow
question per claim:

    Does this quoted evidence actually support this claim?

Kept deliberately separate from extraction. The extractor is asked to be
comprehensive, which pushes it toward over-reaching; the verifier is asked only
to falsify, and is given no incentive to preserve anything. Claims that come
back NOT_SUPPORTED are converted to UNKNOWN rather than silently deleted, so
the audit trail records that something was proposed and rejected.

Note the division of labour with `spans.locate_span`: the span locator answers
"does this quote exist in the text?" deterministically, while the verifier
answers "granting the quote exists, does it license this claim?". Only claims
that pass the first check are worth spending tokens on here.
"""

from __future__ import annotations

from typing import Any

from schemas.models import Claim, ClaimStatus, Verdict, VerificationSummary

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["SUPPORTED", "NOT_SUPPORTED", "AMBIGUOUS"]},
                    "reason": {"type": "string", "description": "One sentence."},
                },
            },
        }
    },
}

SYSTEM = """You are a strict verifier auditing claims extracted from a medical case narrative.

For each claim you are given the quoted evidence that was cited for it. Decide only
whether that quote genuinely supports that specific claim.

- SUPPORTED: the quote directly states the claim.
- NOT_SUPPORTED: the quote does not state the claim, concerns something else, or the
  claim adds specifics (a dose, a date, a causal link) the quote does not contain.
- AMBIGUOUS: the quote is related but does not settle the claim.

You are auditing, not assisting. Do not be charitable, do not repair a weak claim, and
do not use outside clinical knowledge -- only the narrative and the quote. A claim that
is clinically plausible but not stated in the quote is NOT_SUPPORTED."""


def verify(client, *, narrative: str, claims: list[Claim], case_id: str | None) -> list[Claim]:
    """Verify every grounded claim in one batched call, mutating claims in place."""
    targets = [
        c for c in claims if c.status is ClaimStatus.SUPPORTED and c.span and c.span.located
    ]
    if not targets:
        return claims

    block = "\n\n".join(
        f"id: {c.id}\nclaim: {c.claim}\nvalue: {c.value}\ncited evidence: \"{c.evidence_text}\""
        for c in targets
    )
    user = (
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        f"Audit each claim below.\n\n{block}"
    )

    raw = client.complete_json(
        stage="verification",
        system=SYSTEM,
        user=user,
        schema=SCHEMA,
        schema_name="evidence_verification",
        case_id=case_id,
    )

    by_id = {r.get("id"): r for r in raw.get("verdicts", [])}
    for claim in targets:
        row = by_id.get(claim.id)
        if not row:
            # No verdict returned: treat as unverified rather than verified.
            claim.verdict = Verdict.AMBIGUOUS
            claim.verdict_reason = "Verifier returned no verdict for this claim."
            continue

        claim.verdict = Verdict(row.get("verdict", "AMBIGUOUS"))
        claim.verdict_reason = row.get("reason", "")

        if claim.verdict is Verdict.NOT_SUPPORTED:
            claim.status = ClaimStatus.UNKNOWN
            claim.dropped = True
            claim.drop_reason = claim.verdict_reason or "Cited evidence does not support this claim."
            claim.value = None

    return claims


def summarize(claims: list[Claim]) -> VerificationSummary:
    s = VerificationSummary(total_claims=len(claims))
    for c in claims:
        if c.span is not None and not c.span.located:
            s.unlocatable_spans += 1
        if c.verdict is Verdict.SUPPORTED:
            s.supported += 1
        elif c.verdict is Verdict.NOT_SUPPORTED:
            s.not_supported += 1
        elif c.verdict is Verdict.AMBIGUOUS:
            s.ambiguous += 1
        if c.dropped:
            s.dropped += 1
    return s
