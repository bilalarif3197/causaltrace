"""RUCAM weights and refusal conditions, pinned to the published manual.

Transcription errors in a scoring table are silent and change every downstream
number, so the point ranges are asserted against the manual's own summary
(NBK548272) rather than trusted.

The refusal cases matter as much as the arithmetic. RUCAM is explicitly not
calculable when injury preceded exposure, when onset is too long after
withdrawal, or when time to onset is unknown -- and it cannot be applied at all
without an injury pattern. Producing a number in those situations would be
worse than producing nothing.
"""

from __future__ import annotations

import pytest

from services.rucam import (
    CATEGORIES,
    CATEGORIES_BY_KEY,
    MAX_TOTAL,
    MIN_TOTAL,
    classify,
    is_hepatic_event,
    pattern_from_r,
    r_ratio,
    score,
)

# The manual's own summary of the seven categories.
EXPECTED_RANGES = {
    "time_to_onset": {1, 2},
    "course": {-2, 0, 1, 2, 3},
    "risk_alcohol": {0, 1},
    "risk_age": {0, 1},
    "concomitant": {0, -1, -2, -3},
    "nondrug_causes": {-3, -2, 0, 1, 2},
    "previous_information": {0, 1, 2},
    "readministration": {-2, 0, 1, 3},
}


def full(pattern="HEPATOCELLULAR", **overrides) -> dict[str, str]:
    base = {
        "time_to_onset": "suggestive",
        "course": "fall_8_days" if pattern == "HEPATOCELLULAR" else "fall_180_days",
        "risk_alcohol": "no",
        "risk_age": "no",
        "concomitant": "none",
        "nondrug_causes": "all_groups_excluded",
        "previous_information": "in_label",
        "readministration": "not_done",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", CATEGORIES, ids=lambda c: c.key)
def test_category_points_match_the_published_ranges(category):
    """Scoreable options must stay inside the published range.

    Options that block scoring are excluded: they do not contribute a score at
    all, they stop a RUCAM being produced. Time to onset is the case in point --
    the manual says "only +1 or +2 are possible", and its three zero-valued
    options are the "unrelated" and "insufficiently documented" outcomes.
    """
    observed = set()
    for option in category.options:
        if option.blocks_scoring:
            continue
        for pattern in ("HEPATOCELLULAR", "CHOLESTATIC", "MIXED"):
            observed.add(option.score(pattern))
    allowed = EXPECTED_RANGES[category.key]
    assert observed <= allowed, (
        f"{category.key}: produces {sorted(observed - allowed)}, outside the published "
        f"range {sorted(allowed)}"
    )
    assert observed, f"{category.key} has no scoreable options"


def test_bands_are_exactly_as_published():
    # "0 or less 'excluded'; 1 to 2 'unlikely'; 3 to 5 'possible';
    #  6 to 8 'probable'; greater than 8 'highly probable'."
    assert classify(-9) == "Excluded"
    assert classify(0) == "Excluded"
    assert classify(1) == "Unlikely"
    assert classify(2) == "Unlikely"
    assert classify(3) == "Possible"
    assert classify(5) == "Possible"
    assert classify(6) == "Probable"
    assert classify(8) == "Probable"
    assert classify(9) == "Highly probable"
    assert classify(14) == "Highly probable"


def test_cholestatic_course_range_is_narrower():
    """The manual: for cholestatic and mixed injury the course range is 0 to +2,
    not -2 to +3."""
    course = CATEGORIES_BY_KEY["course"]
    for pattern in ("CHOLESTATIC", "MIXED"):
        points = {o.score(pattern) for o in course.options}
        assert min(points) == 0, f"{pattern} course should not go negative"
        assert max(points) == 2, f"{pattern} course should not exceed +2"
    hepatic = {o.score("HEPATOCELLULAR") for o in course.options}
    assert min(hepatic) == -2 and max(hepatic) == 3


def test_total_stays_inside_the_published_range():
    best = score(
        full(course="fall_8_days", risk_alcohol="yes", risk_age="yes", readministration="positive_alone"),
        "HEPATOCELLULAR",
    )
    assert best["total"] <= MAX_TOTAL
    worst = score(
        full(
            time_to_onset="compatible",
            course="no_fall",
            concomitant="other_drug_proven",
            nondrug_causes="other_disease_probable",
            previous_information="unknown_reaction",
            readministration="negative",
        ),
        "HEPATOCELLULAR",
    )
    assert worst["total"] >= MIN_TOTAL


# ---------------------------------------------------------------------------
# R ratio and pattern
# ---------------------------------------------------------------------------


def test_r_ratio_follows_the_published_formula():
    # R = (ALT/ALT ULN) / (ALP/ALP ULN)
    assert r_ratio(alt=684, alt_uln=40, alp=142, alp_uln=120) == pytest.approx(14.45, abs=0.01)


def test_r_ratio_is_none_without_the_inputs():
    assert r_ratio(684, 40, 0, 120) is None
    assert r_ratio(684, 0, 142, 120) is None


def test_pattern_thresholds():
    assert pattern_from_r(17.9) == "HEPATOCELLULAR"  # R > 5
    assert pattern_from_r(5.1) == "HEPATOCELLULAR"
    assert pattern_from_r(4.0) == "MIXED"  # 2 to 5
    assert pattern_from_r(2.0) == "MIXED"
    assert pattern_from_r(1.9) == "CHOLESTATIC"  # R < 2
    assert pattern_from_r(None) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Refusal to score -- as important as the arithmetic
# ---------------------------------------------------------------------------


def test_unknown_pattern_blocks_scoring():
    result = score(full(), "UNKNOWN")
    assert result["calculable"] is False
    assert result["total"] is None
    assert any("pattern is unknown" in r for r in result["blocking_reasons"])


def test_injury_before_exposure_blocks_scoring():
    result = score(full(time_to_onset="before_drug"), "HEPATOCELLULAR")
    assert result["calculable"] is False
    assert result["total"] is None
    assert any("preceded exposure" in r for r in result["blocking_reasons"])


def test_onset_long_after_withdrawal_blocks_scoring():
    result = score(full(time_to_onset="too_late"), "HEPATOCELLULAR")
    assert result["calculable"] is False
    assert any("after withdrawal" in r for r in result["blocking_reasons"])


def test_unknown_onset_blocks_scoring():
    """'Insufficiently documented' in the manual's terms."""
    result = score(full(time_to_onset="unknown"), "HEPATOCELLULAR")
    assert result["calculable"] is False
    assert any("insufficiently" in r.lower() for r in result["blocking_reasons"])


def test_unanswered_categories_are_reported_not_guessed():
    answers = full()
    del answers["nondrug_causes"]
    result = score(answers, "HEPATOCELLULAR")
    assert "nondrug_causes" in result["unanswered"]
    assert result["per_category"]["nondrug_causes"] == 0


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,expected",
    [
        ("Acute liver injury", True),
        ("Drug-induced hepatitis", True),
        ("Cholestatic jaundice", True),
        ("Elevated transaminases", True),
        ("Maculopapular rash", False),
        ("Acute kidney injury", False),
        ("Agranulocytosis", False),
    ],
)
def test_rucam_is_offered_only_for_hepatic_events(event, expected):
    """It is a liver-specific instrument; offering it for a rash would be wrong."""
    assert is_hepatic_event(event) is expected


def test_a_worked_hepatocellular_case():
    """Suggestive onset, rapid dechallenge, labelled hepatotoxin, alternatives
    excluded, no rechallenge: 2+3+0+0+0+2+2+0 = 9 -> highly probable."""
    result = score(full(), "HEPATOCELLULAR")
    assert result["per_category"] == {
        "time_to_onset": 2,
        "course": 3,
        "risk_alcohol": 0,
        "risk_age": 0,
        "concomitant": 0,
        "nondrug_causes": 2,
        "previous_information": 2,
        "readministration": 0,
    }
    assert result["total"] == 9
    assert result["classification"] == "Highly probable"


def test_ai_answers_alone_do_not_score():
    """The same guarantee as Naranjo, at the workspace level.

    Verified live: with all eight categories suggested by the model and a known
    hepatocellular pattern, the total was 0 until a human accepted them.
    """
    from schemas.review import ReviewerStatus
    from services import store, workspace

    doc = workspace.create_case(
        narrative="Patient developed liver injury after starting the drug.",
        suspected_drug="TMP-SMX",
        adverse_event="Acute liver injury",
    )
    workspace.set_rucam_labs(doc, alt=684, alt_uln=40, alp=142, alp_uln=120)
    assessment = workspace.ensure_rucam(doc)
    assert assessment.pattern == "HEPATOCELLULAR"
    assert assessment.calculable is True

    # Populate every AI answer with the most favourable option available.
    for answer in assessment.answers:
        answer.ai_answer = {
            "time_to_onset": "suggestive",
            "course": "fall_8_days",
            "risk_alcohol": "yes",
            "risk_age": "yes",
            "concomitant": "none",
            "nondrug_causes": "all_groups_excluded",
            "previous_information": "in_label",
            "readministration": "positive_alone",
        }[answer.category]
    store.save_case(doc)

    assert workspace.ensure_rucam(doc).total == 0, "AI answers must not score"

    # Now the reviewer confirms one of them.
    workspace.apply_review(doc, "rucam", "previous_information", value="in_label")
    assert workspace.ensure_rucam(doc).total == 2


def test_rucam_rejects_an_option_that_does_not_exist():
    from services import workspace

    doc = workspace.create_case(
        narrative="x", suspected_drug="D", adverse_event="Acute liver injury"
    )
    with pytest.raises(workspace.WorkspaceError, match="not a valid option"):
        workspace.apply_review(doc, "rucam", "course", value="miraculous_recovery")


def test_concomitant_hepatotoxin_pulls_the_score_down():
    with_alt = score(full(concomitant="known_hepatotoxin_compatible"), "HEPATOCELLULAR")
    clean = score(full(), "HEPATOCELLULAR")
    assert with_alt["total"] == clean["total"] - 2
    assert with_alt["classification"] == "Probable"
