"""Deterministic computation over a reviewed case.

Nothing in this module calls a model. Given a case document it produces the
Naranjo framework result and the review statistics, in ordinary Python, so the
numbers are reproducible and cheap enough to recompute on every keystroke.

The load-bearing rule: `score_framework` reads `reviewer_answer` and never
`ai_answer`. An item the reviewer has not answered counts as UNKNOWN and scores
zero, no matter how confident the AI was. That is the difference between a
framework populated *from* expert review and one merely displayed *alongside*
it, and it is why `unreviewed_count` is reported next to the total.
"""

from __future__ import annotations

from schemas.review import (
    Answer,
    AssessmentLevel,
    CONFIRMED_STATUSES,
    CaseDocument,
    EvidenceValence,
    Fact,
    FrameworkResult,
    MissingEvidenceStatus,
    NaranjoReviewItem,
    ReviewerStatus,
    ReviewStats,
    Verdict,
)
from services.naranjo import ITEMS_BY_NUMBER, NARANJO_ITEMS, classify

MIN_POSSIBLE = -4
MAX_POSSIBLE = 13


def _weights(number: int) -> dict[Answer, int]:
    spec = ITEMS_BY_NUMBER[number]
    return {Answer.YES: spec.yes, Answer.NO: spec.no, Answer.UNKNOWN: spec.unknown}


def blank_naranjo_items() -> list[NaranjoReviewItem]:
    """Ten unanswered items, so the questionnaire exists before any AI runs."""
    return [
        NaranjoReviewItem(
            number=spec.number,
            question=spec.question,
            commonly_unknown=spec.commonly_unknown,
            reviewer_answer=Answer.UNKNOWN,
            reviewer_status=ReviewerStatus.NEEDS_REVIEW,
        )
        for spec in NARANJO_ITEMS
    ]


def score_framework(items: list[NaranjoReviewItem]) -> FrameworkResult:
    """Total the reviewer's answers. Mutates each item's `score` in place."""
    total = floor = ceiling = 0
    unknown = unreviewed = 0

    for item in items:
        weights = _weights(item.number)
        item.score = weights[item.reviewer_answer]
        item.commonly_unknown = ITEMS_BY_NUMBER[item.number].commonly_unknown
        total += item.score

        if item.reviewer_answer is Answer.UNKNOWN:
            unknown += 1
            # If resolved, this item would take either its YES or its NO weight.
            floor += min(weights[Answer.YES], weights[Answer.NO])
            ceiling += max(weights[Answer.YES], weights[Answer.NO])
        else:
            floor += item.score
            ceiling += item.score

        if item.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
            unreviewed += 1

    return FrameworkResult(
        total_score=total,
        classification=classify(total),  # type: ignore[arg-type]
        unknown_count=unknown,
        unreviewed_count=unreviewed,
        score_floor=floor,
        score_ceiling=ceiling,
        classification_is_stable=classify(floor) == classify(ceiling),
    )


def confirmed_facts(doc: CaseDocument) -> list[Fact]:
    """Facts the reviewer has accepted or modified -- the only usable evidence."""
    return [f for f in doc.facts if f.reviewer_status in CONFIRMED_STATUSES]


def confirmed_evidence_digest(doc: CaseDocument) -> str:
    """A compact, reviewer-confirmed-only view of the case.

    This is what gets handed to the rationale drafter and the later suggestion
    passes, so that AI text is generated from what the human signed off on
    rather than from the model's own earlier guesses.
    """
    lines: list[str] = []

    facts = confirmed_facts(doc)
    if facts:
        lines.append("REVIEWER-CONFIRMED FACTS:")
        for fact in facts:
            quote = fact.ai.evidence_text if fact.ai else None
            suffix = f'  [source: "{quote}"]' if quote else ""
            lines.append(f"- {fact.label}: {fact.confirmed_value}{suffix}")

    events = [e for e in doc.timeline if e.reviewer_status in CONFIRMED_STATUSES]
    if events:
        lines.append("\nCONFIRMED TIMELINE:")
        for event in sorted(events, key=lambda e: e.order_index):
            when = event.display_date or event.relative_text or "timing not stated"
            flag = " (timing uncertain)" if event.timing_uncertain else ""
            lines.append(f"- {when}: {event.label}{flag}")

    dims = [d for d in doc.dimensions if d.reviewer_status in CONFIRMED_STATUSES]
    if dims:
        lines.append("\nCONFIRMED CAUSALITY DIMENSIONS:")
        for dim in dims:
            lines.append(f"- [{dim.dimension.value}] {dim.question} -> {dim.confirmed_value}")

    assessed = [h for h in doc.hypotheses if h.reviewer_assessment]
    if assessed:
        lines.append("\nREVIEWER-ASSESSED HYPOTHESES:")
        for hyp in assessed:
            lines.append(f"- {hyp.label}: {hyp.reviewer_assessment.value}")
            for valence, tag in (
                (EvidenceValence.SUPPORTING, "for"),
                (EvidenceValence.CONTRADICTING, "against"),
            ):
                for item in hyp.bucket(valence):
                    if item.reviewer_status in CONFIRMED_STATUSES:
                        lines.append(f"    ({tag}) {item.statement}")

    answered = [i for i in doc.naranjo if i.reviewer_status in CONFIRMED_STATUSES]
    if answered:
        lines.append("\nREVIEWER NARANJO ANSWERS:")
        for item in answered:
            lines.append(f"- Item {item.number} ({item.question}) -> {item.reviewer_answer.value}")

    unresolved = [
        m for m in doc.missing_evidence if m.status in (MissingEvidenceStatus.OPEN, MissingEvidenceStatus.UNAVAILABLE)
    ]
    if unresolved:
        lines.append("\nINFORMATION NOT AVAILABLE:")
        for item in unresolved:
            lines.append(f"- {item.prompt}")

    return "\n".join(lines) if lines else "(No reviewer-confirmed evidence yet.)"


def compute_stats(doc: CaseDocument) -> ReviewStats:
    stats = ReviewStats()

    stats.facts_total = len(doc.facts)
    for fact in doc.facts:
        if fact.reviewer_status is ReviewerStatus.ACCEPTED:
            stats.facts_accepted += 1
        elif fact.reviewer_status is ReviewerStatus.MODIFIED:
            stats.facts_modified += 1
        elif fact.reviewer_status is ReviewerStatus.REJECTED:
            stats.facts_rejected += 1
        elif fact.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
            stats.facts_pending += 1
        if fact.ai and fact.ai.verification is Verdict.NOT_SUPPORTED:
            stats.facts_unsupported += 1

    stats.timeline_total = len(doc.timeline)
    stats.timeline_pending = sum(
        1 for e in doc.timeline if e.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW)
    )

    stats.dimensions_total = len(doc.dimensions)
    stats.dimensions_pending = sum(
        1 for d in doc.dimensions if d.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW)
    )

    stats.hypotheses_total = len(doc.hypotheses)
    stats.hypotheses_assessed = sum(1 for h in doc.hypotheses if h.reviewer_assessment)
    stats.hypotheses_retained = sum(
        1
        for h in doc.hypotheses
        if h.reviewer_assessment
        and h.reviewer_assessment
        not in (AssessmentLevel.NOT_SUPPORTED, AssessmentLevel.INSUFFICIENT)
    )

    stats.missing_total = len(doc.missing_evidence)
    stats.missing_open = sum(1 for m in doc.missing_evidence if m.status is MissingEvidenceStatus.OPEN)

    stats.naranjo_reviewed = sum(1 for i in doc.naranjo if i.reviewer_status in CONFIRMED_STATUSES)
    stats.naranjo_pending = sum(
        1 for i in doc.naranjo if i.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW)
    )

    # "Reviewer correction rate": how often the human had to change or discard
    # what the AI proposed. A headline evaluation metric for AI assistance --
    # only AI-originated items count, since a reviewer's own entry is not a
    # correction of anything.
    suggestions = 0
    corrections = 0

    def tally(has_ai: bool, status: ReviewerStatus) -> None:
        nonlocal suggestions, corrections
        if not has_ai:
            return
        suggestions += 1
        if status in (ReviewerStatus.MODIFIED, ReviewerStatus.REJECTED):
            corrections += 1

    for fact in doc.facts:
        tally(fact.ai is not None, fact.reviewer_status)
    for event in doc.timeline:
        tally(event.ai is not None, event.reviewer_status)
    for dim in doc.dimensions:
        tally(dim.ai is not None, dim.reviewer_status)
    for hyp in doc.hypotheses:
        if hyp.ai_assessment is not None:
            suggestions += 1
            if hyp.reviewer_assessment and hyp.reviewer_assessment != hyp.ai_assessment:
                corrections += 1
        for item in hyp.evidence:
            tally(item.ai is not None, item.reviewer_status)
    for item in doc.naranjo:
        if item.ai_answer is not None:
            suggestions += 1
            if item.reviewer_status in CONFIRMED_STATUSES and item.reviewer_answer != item.ai_answer:
                corrections += 1

    stats.ai_suggestions_total = suggestions
    stats.reviewer_corrections = corrections
    return stats
