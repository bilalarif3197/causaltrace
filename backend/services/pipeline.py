"""Pipeline orchestration.

Stage order matters and is load-bearing:

  1. extract      pull grounded facts, demoting any unlocatable citation
  2. verify       independently audit those facts, demoting what fails
  3. timeline     reconstruct sequence (relative ordering preserved)
  4. hypotheses   enumerate competing causes
  5. naranjo      answer 10 items, then score them in pure Python
  6. who_umc      optional structured judgement

Verification runs before the user ever sees a claim, and the Naranjo answers
are independently span-checked inside `naranjo.answer_items`, so an ungrounded
assertion cannot reach the score by any path.
"""

from __future__ import annotations

import time
import uuid

from schemas.models import AnalysisResult, AnalyzeRequest, ClaimStatus
from services import cases, extractor, hypotheses, naranjo, timeline, verifier, who_umc


def run_analysis(client, req: AnalyzeRequest) -> AnalysisResult:
    started = time.perf_counter()
    warnings: list[str] = []

    narrative = req.narrative.strip()
    case_id = req.case_id

    # Mock mode is keyed by case id; recover it from the narrative when the
    # client did not send one.
    if case_id is None:
        matched = cases.match_narrative(narrative)
        case_id = matched.case_id if matched else f"adhoc-{uuid.uuid4().hex[:8]}"

    claims = extractor.extract(
        client,
        narrative=narrative,
        suspected_drug=req.suspected_drug,
        adverse_event=req.adverse_event,
        case_id=case_id,
    )

    unlocatable = sum(1 for c in claims if c.span is not None and not c.span.located)
    if unlocatable:
        warnings.append(
            f"{unlocatable} extracted claim(s) cited text that does not appear in the narrative "
            "and were demoted to UNKNOWN."
        )

    claims = verifier.verify(client, narrative=narrative, claims=claims, case_id=case_id)
    verification = verifier.summarize(claims)
    if verification.not_supported:
        warnings.append(
            f"{verification.not_supported} claim(s) failed independent verification and were "
            "converted to UNKNOWN."
        )

    events = timeline.build(
        client,
        narrative=narrative,
        suspected_drug=req.suspected_drug,
        adverse_event=req.adverse_event,
        case_id=case_id,
    )

    hyps, indistinguishable, note = hypotheses.generate(
        client,
        narrative=narrative,
        suspected_drug=req.suspected_drug,
        adverse_event=req.adverse_event,
        case_id=case_id,
    )
    if indistinguishable:
        warnings.append(
            "The evidence does not distinguish between the leading hypotheses."
            + (f" {note}" if note else "")
        )

    items = naranjo.answer_items(
        client,
        narrative=narrative,
        suspected_drug=req.suspected_drug,
        adverse_event=req.adverse_event,
        case_id=case_id,
    )
    naranjo_result = naranjo.score_items(items)  # deterministic, pure Python

    if not naranjo_result.classification_is_stable:
        warnings.append(
            f"{naranjo_result.unknown_count} Naranjo items are UNKNOWN. Depending on how they "
            f"resolved, the total could fall anywhere from {naranjo_result.score_floor} to "
            f"{naranjo_result.score_ceiling}, so the headline classification is not stable."
        )

    umc = None
    if req.run_who_umc:
        umc = who_umc.assess(
            client,
            narrative=narrative,
            suspected_drug=req.suspected_drug,
            adverse_event=req.adverse_event,
            case_id=case_id,
        )

    grounded = sum(1 for c in claims if c.status is ClaimStatus.SUPPORTED)
    if claims and grounded == 0:
        warnings.append("No claim in this narrative could be grounded in source text.")

    # If the provider could not honour strict JSON schema, say so. Output in a
    # degraded mode is not schema-enforced, which the reader should know.
    for note in getattr(client, "notes", []):
        if note not in warnings:
            warnings.append(note)

    return AnalysisResult(
        case_id=case_id,
        narrative=narrative,
        suspected_drug=req.suspected_drug,
        adverse_event=req.adverse_event,
        claims=claims,
        timeline=events,
        hypotheses=hyps,
        naranjo=naranjo_result,
        who_umc=umc,
        verification=verification,
        unsupported_assertion_rate=round(verification.unsupported_assertion_rate, 4),
        mode=client.mode,  # type: ignore[arg-type]
        model=client.name,
        warnings=warnings,
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )
