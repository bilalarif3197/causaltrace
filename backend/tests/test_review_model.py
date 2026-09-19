"""Tests for the reviewer-control guarantees.

These encode the product's central claim: the AI proposes, the reviewer
decides, and no assessment is ever built from unreviewed machine output. If
any of these fail, the thing has quietly become an autonomous classifier with
a confirmation dialog on top.
"""

from __future__ import annotations

import pytest

from schemas.review import (
    AiSuggestion,
    Answer,
    AssessmentLevel,
    CaseDocument,
    Fact,
    FactSection,
    NaranjoReviewItem,
    Origin,
    ReviewerStatus,
    Verdict,
)
from services import store, workspace
from services.assessment import (
    blank_naranjo_items,
    compute_stats,
    confirmed_evidence_digest,
    confirmed_facts,
    score_framework,
)


def make_fact(value="March 2", status=ReviewerStatus.AI_SUGGESTED, reviewer_value=None) -> Fact:
    return Fact(
        id="fact-1",
        section=FactSection.DRUG_EXPOSURE,
        field="start_date",
        label="Start date",
        ai=AiSuggestion(value=value, evidence_text="began TMP-SMX on March 2", confidence=0.9),
        reviewer_status=status,
        reviewer_value=reviewer_value,
        origin=Origin.AI,
    )


# ---------------------------------------------------------------------------
# confirmed_value: the gate between suggestion and evidence
# ---------------------------------------------------------------------------


def test_unreviewed_suggestion_is_not_evidence():
    """The whole product rests on this: an AI suggestion nobody has looked at
    contributes nothing downstream."""
    fact = make_fact()
    assert fact.confirmed_value is None
    assert fact.is_confirmed is False
    assert fact.needs_attention is True


def test_accepted_suggestion_becomes_evidence():
    fact = make_fact(status=ReviewerStatus.ACCEPTED)
    assert fact.confirmed_value == "March 2"
    assert fact.is_confirmed is True


def test_modified_suggestion_uses_the_reviewer_value():
    fact = make_fact(status=ReviewerStatus.MODIFIED, reviewer_value="March 3")
    assert fact.confirmed_value == "March 3"
    assert fact.ai.value == "March 2", "the AI suggestion must survive unchanged"


def test_rejected_suggestion_contributes_nothing():
    fact = make_fact(status=ReviewerStatus.REJECTED)
    assert fact.confirmed_value is None
    assert fact.is_confirmed is False


def test_apply_review_never_mutates_the_ai_suggestion():
    fact = make_fact()
    original = fact.ai.model_dump()
    fact.apply_review(ReviewerStatus.MODIFIED, "March 5", note="date misread")
    assert fact.ai.model_dump() == original
    assert fact.reviewer_value == "March 5"
    assert fact.reviewer_note == "date misread"
    assert fact.reviewed_at is not None


def test_rejecting_clears_any_previous_reviewer_value():
    fact = make_fact()
    fact.apply_review(ReviewerStatus.MODIFIED, "March 5")
    fact.apply_review(ReviewerStatus.REJECTED)
    assert fact.reviewer_value is None
    assert fact.confirmed_value is None


# ---------------------------------------------------------------------------
# Naranjo scores only from reviewer answers
# ---------------------------------------------------------------------------


def test_blank_questionnaire_scores_zero_and_reports_unreviewed():
    result = score_framework(blank_naranjo_items())
    assert result.total_score == 0
    assert result.unreviewed_count == 10
    assert (result.score_floor, result.score_ceiling) == (-4, 13)
    assert result.classification_is_stable is False


def test_ai_answer_alone_does_not_move_the_score():
    """An AI YES on item 2 is worth +2 only once a human agrees."""
    items = blank_naranjo_items()
    items[1].ai_answer = Answer.YES
    items[1].ai = AiSuggestion(value="YES", evidence_text="started on March 2")
    assert score_framework(items).total_score == 0

    items[1].reviewer_answer = Answer.YES
    items[1].reviewer_status = ReviewerStatus.ACCEPTED
    assert score_framework(items).total_score == 2


def test_reviewer_can_overrule_the_ai_downward():
    items = blank_naranjo_items()
    for item in items:
        item.ai_answer = Answer.YES
        item.reviewer_answer = Answer.YES
        item.reviewer_status = ReviewerStatus.ACCEPTED
    high = score_framework(items).total_score

    # Reviewer disagrees with item 4 (rechallenge, +2 -> 0).
    items[3].reviewer_answer = Answer.UNKNOWN
    items[3].reviewer_status = ReviewerStatus.MODIFIED
    assert score_framework(items).total_score == high - 2


def test_score_always_inside_the_resolved_range():
    import random

    rng = random.Random(7)
    for _ in range(200):
        items = blank_naranjo_items()
        for item in items:
            item.reviewer_answer = rng.choice(list(Answer))
            item.reviewer_status = ReviewerStatus.ACCEPTED
        result = score_framework(items)
        assert result.score_floor <= result.total_score <= result.score_ceiling


# ---------------------------------------------------------------------------
# Confirmed-evidence digest
# ---------------------------------------------------------------------------


def base_doc() -> CaseDocument:
    return CaseDocument(
        id="case-test",
        narrative="The patient began TMP-SMX on March 2. Five days later she developed fatigue.",
        suspected_drug="TMP-SMX",
        adverse_event="Acute liver injury",
        naranjo=blank_naranjo_items(),
    )


def test_digest_excludes_unreviewed_and_rejected_facts():
    doc = base_doc()
    doc.facts = [
        make_fact(),  # unreviewed
        Fact(
            id="fact-2",
            section=FactSection.ADVERSE_EVENT,
            field="event",
            label="Adverse event",
            ai=AiSuggestion(value="fatigue", evidence_text="she developed fatigue"),
            reviewer_status=ReviewerStatus.ACCEPTED,
        ),
        Fact(
            id="fact-3",
            section=FactSection.OTHER_EXPOSURES,
            field="alcohol",
            label="Alcohol",
            ai=AiSuggestion(value="heavy use", evidence_text="nope"),
            reviewer_status=ReviewerStatus.REJECTED,
        ),
    ]
    assert len(confirmed_facts(doc)) == 1
    digest = confirmed_evidence_digest(doc)
    assert "fatigue" in digest
    assert "heavy use" not in digest, "rejected evidence must never reach downstream AI"
    assert "March 2" not in digest, "unreviewed evidence must never reach downstream AI"


def test_digest_is_explicit_when_nothing_is_confirmed():
    assert "No reviewer-confirmed evidence" in confirmed_evidence_digest(base_doc())


# ---------------------------------------------------------------------------
# Workspace operations + audit
# ---------------------------------------------------------------------------


def test_review_is_persisted_and_audited():
    doc = workspace.create_case(
        narrative="The patient began TMP-SMX on March 2.",
        suspected_drug="TMP-SMX",
        adverse_event="Liver injury",
    )
    doc.facts = [make_fact()]
    store.save_case(doc)

    workspace.apply_review(doc, "fact", "fact-1", status=ReviewerStatus.MODIFIED, value="March 3")

    reloaded = store.get_case(doc.id)
    assert reloaded.facts[0].confirmed_value == "March 3"
    assert reloaded.facts[0].ai.value == "March 2"

    entries = store.get_audit(doc.id)
    actions = [e.action for e in entries]
    assert "CASE_CREATED" in actions and "REVIEW" in actions
    review = next(e for e in entries if e.action == "REVIEW")
    assert review.before["value"] is None
    assert review.after["value"] == "March 3"
    assert review.actor is Origin.REVIEWER


def test_naranjo_review_recomputes_score_immediately():
    doc = workspace.create_case(
        narrative="The patient began TMP-SMX on March 2.",
        suspected_drug="TMP-SMX",
        adverse_event="Liver injury",
    )
    assert workspace.envelope(doc).framework.total_score == 0

    workspace.apply_review(doc, "naranjo", "2", value="YES")
    envelope = workspace.envelope(store.get_case(doc.id))
    assert envelope.framework.total_score == 2
    assert envelope.framework.unreviewed_count == 9


def test_bulk_accept_leaves_explicit_decisions_alone():
    doc = workspace.create_case(
        narrative="x", suspected_drug="D", adverse_event="E"
    )
    doc.facts = [
        make_fact(),
        Fact(
            id="fact-2",
            section=FactSection.DRUG_EXPOSURE,
            field="dose",
            label="Dose",
            ai=AiSuggestion(value="160/800 mg"),
            reviewer_status=ReviewerStatus.REJECTED,
        ),
    ]
    store.save_case(doc)

    doc, count = workspace.bulk_review(doc, "fact", ReviewerStatus.ACCEPTED)
    assert count == 1
    assert doc.facts[0].reviewer_status is ReviewerStatus.ACCEPTED
    assert doc.facts[1].reviewer_status is ReviewerStatus.REJECTED, "must not reverse a decision"


def test_reviewer_added_fact_is_confirmed_and_has_no_ai_suggestion():
    doc = workspace.create_case(narrative="x", suspected_drug="D", adverse_event="E")
    doc, fact = workspace.add_fact(doc, field="alcohol", value="No alcohol use reported")
    assert fact.origin is Origin.REVIEWER
    assert fact.ai is None
    assert fact.confirmed_value == "No alcohol use reported"


def test_correction_rate_counts_only_ai_originated_items():
    doc = workspace.create_case(narrative="x", suspected_drug="D", adverse_event="E")
    doc.facts = [
        make_fact(status=ReviewerStatus.ACCEPTED),
        Fact(id="f2", section=FactSection.DRUG_EXPOSURE, field="dose", label="Dose",
             ai=AiSuggestion(value="80mg"), reviewer_status=ReviewerStatus.REJECTED),
        Fact(id="f3", section=FactSection.DRUG_EXPOSURE, field="route", label="Route",
             ai=None, reviewer_status=ReviewerStatus.MODIFIED, reviewer_value="oral",
             origin=Origin.REVIEWER),
    ]
    stats = compute_stats(doc)
    # Two AI suggestions; one rejected. The reviewer's own entry is not a
    # correction of anything.
    assert stats.ai_suggestions_total == 2
    assert stats.reviewer_corrections == 1
    assert stats.correction_rate == 0.5


def test_unsupported_verification_flags_needs_review_not_deletion():
    """A failed verification must warn, never silently drop the claim."""
    fact = make_fact()
    fact.ai.verification = Verdict.NOT_SUPPORTED
    fact.ai.verification_reason = "The quote says the test was not performed."
    fact.reviewer_status = ReviewerStatus.NEEDS_REVIEW
    assert fact.needs_attention is True
    assert fact.ai.value == "March 2", "the claim stays visible for the reviewer to judge"


def test_conclusion_requires_a_known_hypothesis():
    doc = workspace.create_case(narrative="x", suspected_drug="D", adverse_event="E")
    with pytest.raises(workspace.WorkspaceError):
        workspace.set_conclusion(doc, primary_cause_hypothesis_id="hyp-nope")


def test_signing_off_is_audited():
    doc = workspace.create_case(narrative="x", suspected_drug="D", adverse_event="E")
    workspace.set_conclusion(doc, final_assessment="Possible", reviewer_rationale="Because.", signed_off=True)
    actions = [e.action for e in store.get_audit(doc.id)]
    assert "SIGN_OFF" in actions


def test_assessment_level_must_be_valid():
    doc = workspace.create_case(narrative="x", suspected_drug="D", adverse_event="E")
    doc, hyp = workspace.add_hypothesis(doc, label="Infection")
    with pytest.raises(workspace.WorkspaceError, match="not a valid assessment"):
        workspace.apply_review(doc, "hypothesis", hyp.id, value="Definitely it")

    workspace.apply_review(doc, "hypothesis", hyp.id, value=AssessmentLevel.WEAKLY_SUPPORTED.value)
    assert store.get_case(doc.id).hypotheses[0].reviewer_assessment is AssessmentLevel.WEAKLY_SUPPORTED
