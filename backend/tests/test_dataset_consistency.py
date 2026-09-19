"""Guard the evaluation dataset against contradicting itself.

Written after the reference for the TMP-SMX case was recorded as 5 / Probable
while the item answers beside it summed to 3 / Possible. A reference standard
that disagrees with its own components silently corrupts every metric computed
against it, and hand-entered scores are exactly where that happens.

`pmc_ingest.py` applies the same check to published papers, which turn out to
make this mistake too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.review import Answer
from services.naranjo import ITEMS_BY_NUMBER, classify

DATASET = Path(__file__).resolve().parent.parent.parent / "evaluation" / "cases.json"

CASES = json.loads(DATASET.read_text())["cases"] if DATASET.is_file() else []
WITH_ITEMS = [c for c in CASES if c.get("reference_item_answers")]


def weight(number: int, answer: str) -> int:
    spec = ITEMS_BY_NUMBER[number]
    return {Answer.YES: spec.yes, Answer.NO: spec.no, Answer.UNKNOWN: spec.unknown}[Answer(answer)]


@pytest.mark.skipif(not CASES, reason="evaluation dataset not present")
def test_every_case_has_a_stable_identifier():
    ids = [c["case_id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case_id in the dataset"


@pytest.mark.skipif(not WITH_ITEMS, reason="no cases with item-level references")
@pytest.mark.parametrize("case", WITH_ITEMS, ids=lambda c: c["case_id"])
def test_reference_score_matches_its_own_item_answers(case):
    total = sum(weight(int(n), a) for n, a in case["reference_item_answers"].items())
    expected = case.get("reference_naranjo_score")
    if expected is not None:
        assert total == expected, (
            f"{case['case_id']}: item answers sum to {total} but "
            f"reference_naranjo_score says {expected}"
        )


@pytest.mark.skipif(not WITH_ITEMS, reason="no cases with item-level references")
@pytest.mark.parametrize("case", WITH_ITEMS, ids=lambda c: c["case_id"])
def test_reference_band_matches_its_own_score(case):
    score = case.get("reference_naranjo_score")
    band = case.get("reference_naranjo_category")
    if score is not None and band:
        assert classify(score) == band, (
            f"{case['case_id']}: score {score} maps to '{classify(score)}', not '{band}'"
        )


@pytest.mark.skipif(not WITH_ITEMS, reason="no cases with item-level references")
@pytest.mark.parametrize("case", WITH_ITEMS, ids=lambda c: c["case_id"])
def test_all_ten_items_are_answered(case):
    numbers = {int(n) for n in case["reference_item_answers"]}
    assert numbers == set(range(1, 11)), f"{case['case_id']}: expected items 1-10, got {sorted(numbers)}"


@pytest.mark.skipif(not CASES, reason="evaluation dataset not present")
def test_published_references_carry_a_pmcid():
    """A 'published' reference without an identifier cannot be checked by anyone."""
    for case in CASES:
        if case.get("reference_source") == "published":
            assert case.get("pmcid"), f"{case['case_id']}: published reference with no PMCID"
