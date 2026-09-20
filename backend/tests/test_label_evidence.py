"""Tests for the FDA-label lookup behind Naranjo item 1.

Written after a live run cited the wrong medicine. Asked about oral TMP-SMX,
the unconstrained fallback search returned an ophthalmic product and reported
that liver injury was absent from "the label" -- and asked about the
placeholder "Drug A", it returned a homeopathic silica product. Confidently
citing another drug's label is worse than finding nothing, so every hit is now
confirmed against the label's own names.

No test here touches the network.
"""

from __future__ import annotations

import pytest

from schemas.review import Answer, ReviewerStatus
from services import openfda, store, workspace

REAL = {
    "id": "abc123",
    "set_id": "079c828c",
    "effective_time": "20241217",
    "openfda": {
        "generic_name": ["SULFAMETHOXAZOLE AND TRIMETHOPRIM"],
        "brand_name": ["Sulfamethoxazole and Trimethoprim"],
        "manufacturer_name": ["Some Labs"],
    },
    "adverse_reactions": [
        "ADVERSE REACTIONS Hepatitis (including cholestatic jaundice and hepatic necrosis), "
        "elevation of serum transaminase and bilirubin have been reported."
    ],
}

# The product that caused the original bug: an eye drop with no openfda names.
WRONG_PRODUCT = {
    "id": "wrong",
    "set_id": "000775ae",
    "openfda": {},
    "adverse_reactions": ["ADVERSE REACTIONS Local ocular irritation, lid edema, itching."],
}

HOMEOPATHIC = {
    "id": "silicea",
    "openfda": {"generic_name": ["SILICEA"]},
    "warnings": ["WARNINGS If symptoms persist consult a doctor."],
}


class StubLabelClient:
    mode = "mock"
    name = "stub"

    def __init__(self, quote: str | None, mentions=True):
        self.quote = quote
        self.mentions = mentions

    def complete_json(self, **kw):
        return {"mentions_event": self.mentions, "quote": self.quote, "section": "adverse_reactions",
                "reasoning": "stub"}


# ---------------------------------------------------------------------------
# Token extraction and refusal
# ---------------------------------------------------------------------------


def test_tokens_drop_words_that_carry_no_product_identity():
    assert openfda._tokens("Drug A") == []
    assert openfda._tokens("Drug B, an oral antifungal agent") == []
    assert openfda._tokens("Trimethoprim-sulfamethoxazole (TMP-SMX)") == [
        "trimethoprim",
        "sulfamethoxazole",
    ]


def test_class_labels_are_refused_rather_than_guessed():
    """'Drug A' previously matched a homeopathic silica product."""
    with pytest.raises(openfda.LabelUnavailable, match="class or placeholder"):
        openfda.fetch_label("Drug A")


def test_combination_products_are_searched_in_both_orders():
    """openFDA lists this one as 'SULFAMETHOXAZOLE AND TRIMETHOPRIM'."""
    queries = [q for _, q in openfda._queries("Trimethoprim-sulfamethoxazole")]
    joined = " ".join(queries)
    assert "trimethoprim%20and%20sulfamethoxazole" in joined
    assert "sulfamethoxazole%20and%20trimethoprim" in joined


# ---------------------------------------------------------------------------
# Match confirmation -- the actual bug
# ---------------------------------------------------------------------------


def test_confirms_accepts_the_right_product():
    assert openfda._confirms(REAL, ["trimethoprim", "sulfamethoxazole"]) is True


def test_confirms_rejects_a_product_with_no_names():
    assert openfda._confirms(WRONG_PRODUCT, ["trimethoprim", "sulfamethoxazole"]) is False


def test_confirms_rejects_an_unrelated_product():
    assert openfda._confirms(HOMEOPATHIC, ["trimethoprim"]) is False


def test_fetch_rejects_mismatched_hits_and_says_so(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [WRONG_PRODUCT]})
    with pytest.raises(openfda.LabelUnavailable, match="Rejected mismatched"):
        openfda.fetch_label("trimethoprim-sulfamethoxazole")


def test_fetch_returns_a_confirmed_hit(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    record = openfda.fetch_label("trimethoprim-sulfamethoxazole")
    assert record["id"] == "abc123"


# ---------------------------------------------------------------------------
# Label text + grounding
# ---------------------------------------------------------------------------


def test_label_text_keeps_section_headers_for_traceability():
    text, sections = openfda.label_text(REAL)
    assert "[ADVERSE REACTIONS]" in text
    assert sections == "adverse_reactions"


def test_label_with_no_safety_sections_is_unavailable():
    with pytest.raises(openfda.LabelUnavailable):
        openfda.label_text({"openfda": {}})


def new_case(drug="trimethoprim-sulfamethoxazole"):
    return workspace.create_case(
        narrative="Patient developed liver injury.", suspected_drug=drug, adverse_event="Acute liver injury"
    )


def test_a_verbatim_quote_is_kept_with_a_round_tripping_span(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    quote = "elevation of serum transaminase and bilirubin"
    doc, note = workspace.lookup_label_evidence(StubLabelClient(quote), doc)

    evidence = doc.label_evidence
    assert evidence.mentions_event is True
    assert evidence.quote == quote
    assert evidence.span is not None and evidence.span.located
    assert evidence.label_text[evidence.span.start : evidence.span.end] == quote
    assert "describes this reaction" in note


def test_a_fabricated_quote_is_discarded_and_downgraded(monkeypatch):
    """Same grounding gate as the rest of the app: invented citations go."""
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    doc, _ = workspace.lookup_label_evidence(
        StubLabelClient("causes fulminant hepatic failure in 30% of patients"), doc
    )
    evidence = doc.label_evidence
    assert evidence.quote is None
    assert evidence.mentions_event is None, "an unverifiable claim must not stand as a finding"
    assert "does not appear in the retrieved label" in evidence.reasoning


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mentions", [True, False, None])
def test_lookup_never_answers_naranjo_item_1(monkeypatch, mentions):
    """The whole point: this supplies evidence, it does not score the item."""
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    quote = "elevation of serum transaminase and bilirubin" if mentions else None
    doc, _ = workspace.lookup_label_evidence(StubLabelClient(quote, mentions=mentions), doc)

    item = next(i for i in doc.naranjo if i.number == 1)
    assert item.reviewer_answer is Answer.UNKNOWN
    assert item.score == 0
    assert item.reviewer_status is ReviewerStatus.NEEDS_REVIEW
    assert workspace.envelope(doc).framework.total_score == 0


def test_absence_from_the_label_is_not_a_negative(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    doc, note = workspace.lookup_label_evidence(StubLabelClient(None, mentions=False), doc)
    assert doc.label_evidence.mentions_event is False
    assert "stays UNKNOWN" in note
    assert next(i for i in doc.naranjo if i.number == 1).reviewer_answer is Answer.UNKNOWN


def test_unavailable_label_is_recorded_not_raised(monkeypatch):
    doc = new_case(drug="Drug A")
    doc, note = workspace.lookup_label_evidence(StubLabelClient(None), doc)
    assert doc.label_evidence.label_found is False
    assert "class or placeholder" in doc.label_evidence.unavailable_reason
    assert "No FDA label" in note


def test_lookup_is_audited(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    workspace.lookup_label_evidence(StubLabelClient("elevation of serum transaminase and bilirubin"), doc)
    actions = [e.action for e in store.get_audit(doc.id)]
    assert "LABEL_LOOKUP" in actions


def test_caveat_is_carried_with_the_evidence(monkeypatch):
    monkeypatch.setattr(openfda, "_get", lambda url, key: {"results": [REAL]})
    doc = new_case()
    doc, _ = workspace.lookup_label_evidence(StubLabelClient(None), doc)
    assert "not itself a published case report" in doc.label_evidence.CAVEAT
