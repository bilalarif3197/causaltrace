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
                    "verdict": {"type": "string", "enum": ["SUPPORTED", "NOT_SUPPORTED", "PARTIALLY_SUPPORTED"]},
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
- PARTIALLY_SUPPORTED: the quote is related but does not settle the claim.

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
            claim.verdict = Verdict.PARTIALLY_SUPPORTED
            claim.verdict_reason = "Verifier returned no verdict for this claim."
            continue

        claim.verdict = Verdict(row.get("verdict", "PARTIALLY_SUPPORTED"))
        claim.verdict_reason = row.get("reason", "")

        if claim.verdict is Verdict.NOT_SUPPORTED:
            claim.status = ClaimStatus.UNKNOWN
            claim.dropped = True
            claim.drop_reason = claim.verdict_reason or "Cited evidence does not support this claim."
            claim.value = None

    return claims


NARANJO_SYSTEM = """You are a strict verifier auditing answers to the Naranjo ADR Probability Scale.

For each item you are given the question, the answer given, and the quote cited for it.
Decide only whether that quote establishes that specific answer to that specific item.

- SUPPORTED: the quote directly establishes this answer.
- NOT_SUPPORTED: the quote is about a different proposition, or supports only the general
  topic rather than the claim. Two examples that must be rejected:
    * item 3 (did the event improve after withdrawal) cited to a quote that says only that
      the drug was discontinued -- stopping is not improving;
    * item 4 or 6 answered NO where the quote shows the rechallenge or placebo was never
      performed -- "not done" does not establish "done, and negative".
- PARTIALLY_SUPPORTED: related but does not settle it.

One exception, for a structural reason. Item 5 (alternative causes) answered NO is a
GLOBAL negative: "nothing else could have caused this." A global negative can rarely be
established by a single sentence, so for item 5 only, judge the answer against the WHOLE
narrative, treating the quote as the primary anchor rather than the sole evidence. If the
narrative taken together affirmatively excludes alternatives -- no concomitant drugs, no
relevant history, a workup that ruled other causes out, or a positive rechallenge that no
alternative explains -- then NO is SUPPORTED even though one sentence does not carry it
alone. Every other item is judged on its quote.

Audit, do not assist. Do not repair a weak answer and do not use outside clinical
knowledge beyond the narrative. An answer that is clinically reasonable but not
established by its evidence is NOT_SUPPORTED."""


def verify_answers(client, *, narrative: str, items: list, case_id: str | None) -> list:
    """Audit Naranjo item citations, the same way claims are audited.

    Without this, a Naranjo answer only had to clear the span locator -- i.e. its quote
    had to *exist*, not to be *relevant*. A live run surfaced exactly that gap: item 3
    ("did the event improve after withdrawal?") answered YES on the strength of a quote
    that established only that the drug had been stopped.

    An item whose citation fails is set to UNKNOWN, so it scores 0. The rejected quote
    and the reason are retained for the audit trail rather than discarded, because
    "answered, then rejected, and why" is more useful to a human reviewer than silence.
    """
    from schemas.models import Answer, Verdict as V

    targets = [
        i for i in items if i.answer is not Answer.UNKNOWN and i.span is not None and i.span.located
    ]
    if not targets:
        return items

    block = "\n\n".join(
        f"id: item{i.number}\nitem {i.number}: {i.question}\nanswer given: {i.answer.value}\n"
        f"cited evidence: \"{i.evidence_text}\""
        for i in targets
    )
    raw = client.complete_json(
        stage="naranjo_verification",
        system=NARANJO_SYSTEM,
        user=f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\nAudit each item answer below.\n\n{block}",
        schema=SCHEMA,
        schema_name="naranjo_verification",
        case_id=case_id,
    )

    by_id = {r.get("id"): r for r in raw.get("verdicts", [])}
    for item in targets:
        row = by_id.get(f"item{item.number}")
        if not row:
            item.verdict = V.PARTIALLY_SUPPORTED
            item.verdict_reason = "Verifier returned no verdict for this item."
            continue
        item.verdict = V(row.get("verdict", "PARTIALLY_SUPPORTED"))
        item.verdict_reason = row.get("reason", "")
        if item.verdict is V.NOT_SUPPORTED:
            # An answer whose citation does not establish it must not move the score.
            item.answer = Answer.UNKNOWN
    return items


def summarize(claims: list[Claim]) -> VerificationSummary:
    s = VerificationSummary(total_claims=len(claims))
    for c in claims:
        if c.span is not None and not c.span.located:
            s.unlocatable_spans += 1
        if c.verdict is Verdict.SUPPORTED:
            s.supported += 1
        elif c.verdict is Verdict.NOT_SUPPORTED:
            s.not_supported += 1
        elif c.verdict is Verdict.PARTIALLY_SUPPORTED:
            s.ambiguous += 1
        if c.dropped:
            s.dropped += 1
    return s
