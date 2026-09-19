"""Tests for the deterministic half of the Naranjo implementation.

The scoring table is the one place in CausalTrace where a silent error would be
both invisible and consequential, so it is pinned hard: published weights,
published range, published band boundaries.
"""

from __future__ import annotations

import pytest

from schemas.models import Answer, NaranjoItem
from services.naranjo import (
    MAX_POSSIBLE,
    MIN_POSSIBLE,
    NARANJO_ITEMS,
    classify,
    score_items,
)

# Weights transcribed from the published Naranjo worksheet (yes, no, unknown).
PUBLISHED_WEIGHTS = {
    1: (1, 0, 0),
    2: (2, -1, 0),
    3: (1, 0, 0),
    4: (2, -1, 0),
    5: (-1, 2, 0),
    6: (-1, 1, 0),
    7: (1, 0, 0),
    8: (1, 0, 0),
    9: (1, 0, 0),
    10: (1, 0, 0),
}


def items(answers: dict[int, str]) -> list[NaranjoItem]:
    return [
        NaranjoItem(number=s.number, question=s.question, answer=Answer(answers[s.number]))
        for s in NARANJO_ITEMS
    ]


def test_ten_items():
    assert len(NARANJO_ITEMS) == 10
    assert [s.number for s in NARANJO_ITEMS] == list(range(1, 11))


@pytest.mark.parametrize("number,expected", PUBLISHED_WEIGHTS.items())
def test_weights_match_published_worksheet(number, expected):
    spec = next(s for s in NARANJO_ITEMS if s.number == number)
    assert (spec.yes, spec.no, spec.unknown) == expected


def test_score_range_is_minus_4_to_13():
    """The published scale runs -4..+13; a wrong weight would move these."""
    assert (MIN_POSSIBLE, MAX_POSSIBLE) == (-4, 13)


@pytest.mark.parametrize(
    "score,band",
    [
        (13, "Definite"), (9, "Definite"),
        (8, "Probable"), (5, "Probable"),
        (4, "Possible"), (1, "Possible"),
        (0, "Doubtful"), (-4, "Doubtful"),
    ],
)
def test_band_boundaries(score, band):
    assert classify(score) == band


def test_all_unknown_scores_zero_doubtful():
    result = score_items(items({n: "UNKNOWN" for n in range(1, 11)}))
    assert result.total_score == 0
    assert result.classification == "Doubtful"
    assert result.unknown_count == 10
    # With nothing known, the score could still land anywhere on the scale.
    assert (result.score_floor, result.score_ceiling) == (MIN_POSSIBLE, MAX_POSSIBLE)
    assert result.classification_is_stable is False


def test_maximum_case():
    answers = {1: "YES", 2: "YES", 3: "YES", 4: "YES", 5: "NO",
               6: "NO", 7: "YES", 8: "YES", 9: "YES", 10: "YES"}
    result = score_items(items(answers))
    assert result.total_score == MAX_POSSIBLE == 13
    assert result.classification == "Definite"
    assert result.unknown_count == 0
    assert result.classification_is_stable is True


def test_minimum_case():
    answers = {1: "NO", 2: "NO", 3: "NO", 4: "NO", 5: "YES",
               6: "YES", 7: "NO", 8: "NO", 9: "NO", 10: "NO"}
    assert score_items(items(answers)).total_score == MIN_POSSIBLE == -4


def test_total_always_inside_resolved_range():
    """Invariant: every item's UNKNOWN weight lies between its YES and NO
    weights, so the reported total can never fall outside [floor, ceiling]."""
    import random

    rng = random.Random(1234)
    for _ in range(300):
        answers = {n: rng.choice(["YES", "NO", "UNKNOWN"]) for n in range(1, 11)}
        r = score_items(items(answers))
        assert r.score_floor <= r.total_score <= r.score_ceiling
        assert r.score_floor >= MIN_POSSIBLE
        assert r.score_ceiling <= MAX_POSSIBLE


def test_alternative_cause_swing_is_three_points():
    """Item 5 is the decisive trap: NO instead of YES swings the total by 3 and
    can move the classification band on its own."""
    base = {1: "UNKNOWN", 2: "YES", 3: "YES", 4: "UNKNOWN", 6: "UNKNOWN",
            7: "UNKNOWN", 8: "UNKNOWN", 9: "NO", 10: "YES"}
    with_alt = score_items(items({**base, 5: "YES"}))
    without_alt = score_items(items({**base, 5: "NO"}))
    assert without_alt.total_score - with_alt.total_score == 3
    assert with_alt.classification == "Possible"
    assert without_alt.classification == "Probable"


def test_placebo_unknown_does_not_inflate():
    """Item 6 scored UNKNOWN must not add the point that NO would add."""
    base = {n: "UNKNOWN" for n in range(1, 11)}
    assert score_items(items({**base, 6: "UNKNOWN"})).total_score == 0
    assert score_items(items({**base, 6: "NO"})).total_score == 1


def test_commonly_unknown_flags_are_set_by_scorer():
    result = score_items(items({n: "UNKNOWN" for n in range(1, 11)}))
    flagged = {i.number for i in result.items if i.commonly_unknown}
    # Rechallenge, placebo, drug levels, dose-response.
    assert flagged == {4, 6, 7, 8}
