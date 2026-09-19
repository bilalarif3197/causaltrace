"""Tests for the anti-hallucination layers.

Two independent gates must each be able to stop an ungrounded claim:

  1. `spans.locate_span` -- does this quote exist in the source at all?
  2. `verifier.verify`   -- granting it exists, does it license the claim?

These tests assert that a claim failing either gate cannot end up presented as
SUPPORTED, and that a fabricated Naranjo citation cannot move the score.
"""

from __future__ import annotations

from schemas.models import Answer, AnalyzeRequest, Claim, ClaimStatus, Verdict
from services import naranjo, verifier
from services.extractor import extract
from services.llm_client import MockClient
from services.pipeline import run_analysis
from services.spans import locate_span

NARRATIVE = (
    "The patient started Drug A on 3 January. Two weeks later, ALT rose to 642 U/L. "
    "Hepatitis serologies were not obtained."
)


class StubClient:
    """Returns a fixed payload for any stage; used to inject bad model output."""

    mode = "mock"
    name = "stub"

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, **kwargs):
        return self.payload


# ---------------------------------------------------------------------------
# Span location
# ---------------------------------------------------------------------------


def test_exact_quote_locates():
    span = locate_span(NARRATIVE, "ALT rose to 642 U/L")
    assert span is not None and span.located
    assert span.locator == "exact"
    assert NARRATIVE[span.start : span.end] == "ALT rose to 642 U/L"


def test_whitespace_normalised_quote_locates():
    """Models re-wrap text; that must not read as a fabricated citation."""
    span = locate_span(NARRATIVE, "The patient started   Drug A\n on 3 January")
    assert span is not None and span.located
    assert span.locator in {"normalized", "fuzzy"}
    # Offsets must still slice real source text, not the model's version.
    assert NARRATIVE[span.start : span.end].startswith("The patient started")


def test_curly_quote_variants_locate():
    span = locate_span("She said \u201cno records were available\u201d today.", '"no records were available"')
    assert span is not None and span.located


def test_fabricated_quote_is_unlocatable():
    span = locate_span(NARRATIVE, "A liver biopsy confirmed drug-induced injury")
    assert span is not None
    assert not span.located
    assert span.locator == "unlocatable"


def test_empty_quote_returns_none():
    assert locate_span(NARRATIVE, None) is None
    assert locate_span(NARRATIVE, "   ") is None


def test_offsets_round_trip_for_all_fixture_cases():
    """Every span the API would return must slice back to its own text.

    Scoped to cases that actually have recorded fixtures -- demo cases added
    for the live workspace (e.g. the TMP-SMX case) have none by design.
    """
    from services import cases

    client = MockClient()
    recorded = set(client.available_cases())
    covered = [c for c in cases.EXAMPLE_CASES if c.case_id in recorded]
    assert covered, "no fixture-backed cases to check"

    for case in covered:
        result = run_analysis(
            client,
            AnalyzeRequest(
                narrative=case.narrative,
                suspected_drug=case.suspected_drug,
                adverse_event=case.adverse_event,
                case_id=case.case_id,
            ),
        )
        spans = [c.span for c in result.claims]
        spans += [e.span for e in result.timeline]
        spans += [i.span for i in result.naranjo.items]
        for h in result.hypotheses:
            for bucket in (h.supporting_evidence, h.contradicting_evidence, h.unknown_evidence):
                spans += [i.span for i in bucket]
        checked = 0
        for span in spans:
            if span and span.located:
                assert result.narrative[span.start : span.end] == span.text
                checked += 1
        assert checked > 0, f"{case.case_id} produced no located spans"


# ---------------------------------------------------------------------------
# Gate 1: extraction demotes fabricated citations
# ---------------------------------------------------------------------------


def test_extractor_demotes_claim_with_fabricated_quote():
    client = StubClient(
        {
            "claims": [
                {
                    "slot": "objective_evidence",
                    "claim": "A liver biopsy confirmed drug-induced injury.",
                    "value": "Biopsy confirmed",
                    "evidence_text": "A liver biopsy confirmed drug-induced injury",
                    "confidence": 0.9,
                    "status": "SUPPORTED",
                }
            ]
        }
    )
    claims = extract(
        client, narrative=NARRATIVE, suspected_drug="Drug A", adverse_event="liver injury", case_id=None
    )
    assert len(claims) == 1
    claim = claims[0]
    assert claim.status is ClaimStatus.UNKNOWN
    assert claim.dropped is True
    assert claim.value is None
    assert "could not be located" in claim.drop_reason


def test_extractor_keeps_genuinely_grounded_claim():
    client = StubClient(
        {
            "claims": [
                {
                    "slot": "labs",
                    "claim": "ALT rose markedly.",
                    "value": "642 U/L",
                    "evidence_text": "ALT rose to 642 U/L",
                    "confidence": 0.95,
                    "status": "SUPPORTED",
                }
            ]
        }
    )
    claim = extract(
        client, narrative=NARRATIVE, suspected_drug="Drug A", adverse_event="liver injury", case_id=None
    )[0]
    assert claim.status is ClaimStatus.SUPPORTED
    assert claim.dropped is False


# ---------------------------------------------------------------------------
# Gate 2: verification demotes real quotes that do not support the claim
# ---------------------------------------------------------------------------


def test_verifier_converts_unsupported_claim_to_unknown():
    """The canonical failure: a real quote saying tests were NOT done, cited to
    claim a cause was excluded."""
    claim = Claim(
        id="c000",
        slot="alternative_causes",
        claim="Viral hepatitis was excluded.",
        value="Excluded",
        evidence_text="Hepatitis serologies were not obtained",
        confidence=0.6,
        status=ClaimStatus.SUPPORTED,
        span=locate_span(NARRATIVE, "Hepatitis serologies were not obtained"),
    )
    assert claim.span.located  # gate 1 passes: the quote is genuinely present

    client = StubClient(
        {
            "verdicts": [
                {
                    "id": "c000",
                    "verdict": "NOT_SUPPORTED",
                    "reason": "The quote says serologies were not obtained, which is not exclusion.",
                }
            ]
        }
    )
    [out] = verifier.verify(client, narrative=NARRATIVE, claims=[claim], case_id=None)
    assert out.verdict is Verdict.NOT_SUPPORTED
    assert out.status is ClaimStatus.UNKNOWN
    assert out.dropped is True
    assert out.value is None


def test_missing_verdict_is_ambiguous_not_supported():
    """A claim the verifier ignored must not be treated as verified."""
    claim = Claim(
        id="c000",
        slot="labs",
        claim="ALT rose markedly.",
        value="642 U/L",
        evidence_text="ALT rose to 642 U/L",
        confidence=0.9,
        status=ClaimStatus.SUPPORTED,
        span=locate_span(NARRATIVE, "ALT rose to 642 U/L"),
    )
    [out] = verifier.verify(StubClient({"verdicts": []}), narrative=NARRATIVE, claims=[claim], case_id=None)
    assert out.verdict is Verdict.PARTIALLY_SUPPORTED
    assert out.dropped is False


def test_summary_counts_dropped_and_unlocatable():
    claims = [
        Claim(id="a", slot="labs", claim="x", status=ClaimStatus.UNKNOWN,
              span=locate_span(NARRATIVE, "never appears in the text at all")),
        Claim(id="b", slot="labs", claim="y", status=ClaimStatus.SUPPORTED,
              verdict=Verdict.SUPPORTED, span=locate_span(NARRATIVE, "ALT rose to 642 U/L")),
    ]
    summary = verifier.summarize(claims)
    assert summary.total_claims == 2
    assert summary.unlocatable_spans == 1
    assert summary.supported == 1
    assert summary.unsupported_assertion_rate == 0.5


# ---------------------------------------------------------------------------
# An ungrounded Naranjo answer must not move the score
# ---------------------------------------------------------------------------


def test_naranjo_item_with_real_but_irrelevant_quote_is_rejected():
    """Regression from a live DeepSeek run: item 3 ("did the event improve after
    withdrawal?") was answered YES citing a quote that established only that the
    drug had been stopped. The span locator passes it -- the quote is genuinely in
    the text -- so only the semantic audit can catch it."""
    items = [
        naranjo.NaranjoItem(
            number=3,
            question=naranjo.ITEMS_BY_NUMBER[3].question,
            answer=Answer.YES,
            evidence_text="The patient started Drug A on 3 January",
            span=locate_span(NARRATIVE, "The patient started Drug A on 3 January"),
        )
    ]
    assert items[0].span.located  # gate 1 passes

    client = StubClient(
        {
            "verdicts": [
                {
                    "id": "item3",
                    "verdict": "NOT_SUPPORTED",
                    "reason": "The quote establishes initiation, not improvement after withdrawal.",
                }
            ]
        }
    )
    [out] = verifier.verify_answers(client, narrative=NARRATIVE, items=items, case_id=None)
    assert out.answer is Answer.UNKNOWN
    assert out.verdict is Verdict.NOT_SUPPORTED
    assert "improvement" in out.verdict_reason
    # The rejected quote is retained for the audit trail.
    assert out.evidence_text is not None
    # And it must score zero rather than the +1 a YES would have carried.
    assert naranjo.score_items(
        [out] + [
            naranjo.NaranjoItem(number=n, question=naranjo.ITEMS_BY_NUMBER[n].question)
            for n in range(1, 11) if n != 3
        ]
    ).total_score == 0


def test_naranjo_verification_skips_unknown_items():
    """UNKNOWN answers assert nothing, so there is nothing to audit and no
    reason to spend tokens on them."""
    items = [
        naranjo.NaranjoItem(number=n, question=naranjo.ITEMS_BY_NUMBER[n].question)
        for n in range(1, 11)
    ]

    class Boom:
        mode = "mock"
        name = "boom"

        def complete_json(self, **kwargs):
            raise AssertionError("verifier should not have been called")

    assert verifier.verify_answers(Boom(), narrative=NARRATIVE, items=items, case_id=None) == items


def test_naranjo_answer_with_fabricated_quote_is_forced_to_unknown():
    """Item 4 answered YES (+2) on a fabricated quote must score 0, not +2."""
    payload = {
        "items": [
            {
                "number": 4,
                "answer": "YES",
                "rationale": "The drug was readministered and the reaction recurred.",
                "evidence_text": "Drug A was readministered and ALT rose again",
            }
        ]
        + [
            {"number": n, "answer": "UNKNOWN", "rationale": "", "evidence_text": None}
            for n in range(1, 11)
            if n != 4
        ]
    }
    items = naranjo.answer_items(
        StubClient(payload),
        narrative=NARRATIVE,
        suspected_drug="Drug A",
        adverse_event="liver injury",
        case_id=None,
    )
    item4 = next(i for i in items if i.number == 4)
    assert item4.answer is Answer.UNKNOWN
    assert item4.verdict is Verdict.NOT_SUPPORTED
    assert item4.evidence_text is None

    result = naranjo.score_items(items)
    assert result.total_score == 0
    assert result.classification == "Doubtful"
