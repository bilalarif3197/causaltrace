"""RUCAM — the hepatotoxicity-specific causality instrument.

Weights transcribed from the RUCAM Manual of Operations as published in
LiverTox (NCBI Bookshelf NBK548272), retrieved via the NLM LitArch OAI service
rather than reconstructed from memory. The manual's own summary of the seven
categories is the authority for the point ranges:

    (1) time to onset (+1 or +2); (2) course (-2, 0, +1, +2 or +3); (3) risk
    factors (2 scores: 0 or +1 each); (4) concomitant drugs (0, -1, -2 or -3);
    (5) nondrug causes of liver injury (-3, -2, 0, +1, or +2); (6) previous
    information on the hepatotoxicity of the drug (0, +1, or +2); and
    (7) response to readministration.

Bands, quoted verbatim:

    0 or less indicate that the drug is "excluded" as a cause; 1 to 2 that it is
    "unlikely"; 3 to 5 "possible"; 6 to 8 "probable"; and greater than 8,
    "highly probable".

Two properties make RUCAM harder than Naranjo, and both are honesty features
rather than inconveniences:

  * **Scoring depends on the injury pattern.** The first three categories are
    scored differently for hepatocellular versus cholestatic/mixed injury, and
    the course category has a narrower range for cholestatic/mixed (0 to +2,
    not -2 to +3). The pattern comes from the R ratio, so without ALT and ALP
    the instrument cannot be applied properly.

  * **RUCAM is sometimes not calculable at all.** The manual is explicit: if
    injury began before the drug, or more than 15 days (hepatocellular) or 30
    days (cholestatic/mixed) after stopping it, the case is "unrelated" and a
    RUCAM should not be calculated. If time to onset is unknown the case is
    "insufficiently documented" and again a score must not be produced. This
    module refuses rather than returning a misleading number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Pattern = Literal["HEPATOCELLULAR", "CHOLESTATIC", "MIXED", "UNKNOWN"]

MANUAL_CITATION = (
    "RUCAM Manual of Operations, LiverTox (NIDDK/NLM), NCBI Bookshelf NBK548272. "
    "https://www.ncbi.nlm.nih.gov/books/NBK548272/"
)

#: Hepatic adverse events RUCAM applies to. It is a liver-specific instrument
#: and must not be offered for, say, a cutaneous reaction.
HEPATIC_TERMS = (
    "liver", "hepat", "jaundice", "cholestas", "transaminas", "alt", "ast",
    "bilirubin", "alkaline phosphatase", "cirrhos", "icterus",
)


def is_hepatic_event(adverse_event: str) -> bool:
    text = (adverse_event or "").lower()
    return any(term in text for term in HEPATIC_TERMS)


def r_ratio(alt: float, alt_uln: float, alp: float, alp_uln: float) -> Optional[float]:
    """R = (ALT/ALT ULN) / (ALP/ALP ULN), per the manual."""
    if not (alt_uln and alp_uln and alp):
        return None
    denominator = alp / alp_uln
    if denominator == 0:
        return None
    return round((alt / alt_uln) / denominator, 2)


def pattern_from_r(r: Optional[float]) -> Pattern:
    """R > 5 hepatocellular, R < 2 cholestatic, 2-5 mixed."""
    if r is None:
        return "UNKNOWN"
    if r > 5:
        return "HEPATOCELLULAR"
    if r < 2:
        return "CHOLESTATIC"
    return "MIXED"


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    #: Points by pattern. "*" applies to every pattern.
    points: dict[str, int] = field(default_factory=dict)
    #: When set, choosing this option means RUCAM must not be scored at all.
    blocks_scoring: Optional[str] = None

    def score(self, pattern: Pattern) -> int:
        if self.key in ("unknown", "not_done", "none"):
            return self.points.get("*", 0)
        return self.points.get(pattern, self.points.get("*", 0))


@dataclass(frozen=True)
class Category:
    key: str
    number: int
    title: str
    question: str
    options: tuple[Option, ...]
    note: str = ""

    def option(self, key: str) -> Optional[Option]:
        return next((o for o in self.options if o.key == key), None)


HEPATIC = "HEPATOCELLULAR"
CHOL = "CHOLESTATIC"
MIXED = "MIXED"


def _all(points: int) -> dict[str, int]:
    return {"*": points}


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="time_to_onset",
        number=1,
        title="Time to onset",
        question="How long after starting the drug did the injury begin?",
        note=(
            "Counted from the first day the drug was given to the first symptom, sign or "
            "abnormal test indicating injury. Only +1 or +2 are possible."
        ),
        options=(
            Option("suggestive", "5 to 90 days from first exposure (suggestive)", {HEPATIC: 2, CHOL: 2, MIXED: 2}),
            Option("compatible", "Under 5 or over 90 days (compatible)", {HEPATIC: 1, CHOL: 1, MIXED: 1}),
            Option(
                "after_stopping_compatible",
                "Began after stopping, within 15 days (hepatocellular) or 30 days (cholestatic/mixed)",
                {HEPATIC: 1, CHOL: 1, MIXED: 1},
            ),
            Option(
                "before_drug",
                "Injury began BEFORE the drug was started",
                _all(0),
                blocks_scoring=(
                    "Injury preceded exposure, so the manual classes the case as 'unrelated' "
                    "and a RUCAM must not be calculated."
                ),
            ),
            Option(
                "too_late",
                "Began more than 15 days (hepatocellular) or 30 days (cholestatic/mixed) after stopping",
                _all(0),
                blocks_scoring=(
                    "Onset too long after withdrawal, so the manual classes the case as "
                    "'unrelated' and a RUCAM must not be calculated."
                ),
            ),
            Option(
                "unknown",
                "Time to onset not reported",
                _all(0),
                blocks_scoring=(
                    "Without a time to onset the manual classes the case as 'insufficiently "
                    "documented' and a RUCAM must not be calculated."
                ),
            ),
        ),
    ),
    Category(
        key="course",
        number=2,
        title="Course after stopping",
        question="What happened to the liver tests after the drug was withdrawn?",
        note=(
            "Range is -2 to +3 for hepatocellular injury but only 0 to +2 for cholestatic or "
            "mixed injury. If the drug was continued, this category scores 0."
        ),
        options=(
            Option("fall_8_days", "Fell 50% or more from peak within 8 days", {HEPATIC: 3, CHOL: 0, MIXED: 0}),
            Option("fall_30_days", "Fell 50% or more from peak within 30 days", {HEPATIC: 2, CHOL: 0, MIXED: 0}),
            Option("fall_180_days", "Fell 50% or more within 180 days", {HEPATIC: 0, CHOL: 2, MIXED: 2}),
            Option("partial_fall", "Fell less than 50%, or fell only after 180 days", {HEPATIC: 0, CHOL: 1, MIXED: 1}),
            Option("drug_continued", "Drug was continued", _all(0)),
            Option("no_information", "No follow-up information on the course", _all(0)),
            Option(
                "no_fall",
                "No fall of 50% or more, or a recurrent rise",
                {HEPATIC: -2, CHOL: 0, MIXED: 0},
            ),
        ),
    ),
    Category(
        key="risk_alcohol",
        number=3,
        title="Risk factor: alcohol or pregnancy",
        question="Is there a history of alcohol use (or, for cholestatic/mixed injury, pregnancy)?",
        note="Only one point is available here, even if both alcohol and pregnancy apply.",
        options=(
            Option("yes", "Yes", _all(1)),
            Option("no", "No", _all(0)),
            Option("unknown", "Not reported", _all(0)),
        ),
    ),
    Category(
        key="risk_age",
        number=3,
        title="Risk factor: age",
        question="Is the patient 55 years of age or older?",
        options=(
            Option("yes", "Yes, 55 or older", _all(1)),
            Option("no", "No, under 55", _all(0)),
            Option("unknown", "Age not reported", _all(0)),
        ),
    ),
    Category(
        key="concomitant",
        number=4,
        title="Concomitant drugs",
        question="Were other potentially hepatotoxic agents involved?",
        note="These points are negative: they reflect how much another agent could explain the injury.",
        options=(
            Option("none", "No concomitant drug, or one whose timing is incompatible", _all(0)),
            Option(
                "unknown_hepatotoxin_compatible",
                "A drug NOT known to cause liver injury, with compatible or suggestive timing",
                _all(-1),
            ),
            Option(
                "known_hepatotoxin_compatible",
                "A drug KNOWN to cause liver injury, with compatible or suggestive timing",
                _all(-2),
            ),
            Option(
                "other_drug_proven",
                "Another drug has proven evidence of its role (e.g. positive rechallenge)",
                _all(-3),
            ),
        ),
    ),
    Category(
        key="nondrug_causes",
        number=5,
        title="Non-drug causes",
        question="How thoroughly were other causes of liver injury excluded?",
        note=(
            "Group I is hepatitis A, B and C, biliary obstruction, alcoholic liver disease and "
            "ischaemic hepatitis. Group II covers complications of underlying conditions."
        ),
        options=(
            Option("all_groups_excluded", "All Group I and Group II causes reasonably ruled out", _all(2)),
            Option("group_i_excluded", "All 6 Group I causes ruled out, Group II not", _all(1)),
            Option("four_or_five", "Only 4 or 5 Group I causes ruled out", _all(0)),
            Option("fewer_than_four", "Fewer than 4 Group I causes ruled out", _all(-2)),
            Option("other_disease_probable", "Another liver disease appears highly probable", _all(-3)),
        ),
    ),
    Category(
        key="previous_information",
        number=6,
        title="Previous information on hepatotoxicity",
        question="Is this drug known to cause liver injury?",
        note=(
            "The manual scores +2 specifically when the PRODUCT LABEL states the drug can cause "
            "liver injury, so the FDA label lookup on the Naranjo step is direct evidence here."
        ),
        options=(
            Option("in_label", "The product label states it can cause liver injury", _all(2)),
            Option("published_only", "Not in the label, but cases have been published", _all(1)),
            Option("unknown_reaction", "The reaction is not known to occur with this drug", _all(0)),
        ),
    ),
    Category(
        key="readministration",
        number=7,
        title="Response to readministration",
        question="Was the drug given again, and what happened?",
        note="Rarely performed. 'Not done' scores 0 and is the honest answer in most cases.",
        options=(
            Option("positive_alone", "Re-exposed to this drug alone, and the enzymes doubled", _all(3)),
            Option(
                "positive_during_injury",
                "Reintroduced during the acute injury, and the enzymes doubled",
                _all(1),
            ),
            Option("not_done", "Not re-exposed", _all(0)),
            Option(
                "negative",
                "Re-exposed after recovery with no rise above the upper limit of normal",
                _all(-2),
            ),
        ),
    ),
)

CATEGORIES_BY_KEY = {c.key: c for c in CATEGORIES}

MIN_TOTAL = -9
MAX_TOTAL = 14


def classify(total: int) -> str:
    """Bands quoted from the manual."""
    if total <= 0:
        return "Excluded"
    if total <= 2:
        return "Unlikely"
    if total <= 5:
        return "Possible"
    if total <= 8:
        return "Probable"
    return "Highly probable"


def score(answers: dict[str, str], pattern: Pattern) -> dict:
    """Total RUCAM deterministically from reviewer answers.

    Returns a dict rather than raising, because "not calculable" is a real and
    important RUCAM outcome that the UI must be able to display.
    """
    blocked: list[str] = []
    per_category: dict[str, int] = {}
    unanswered: list[str] = []

    for category in CATEGORIES:
        chosen = answers.get(category.key)
        if not chosen:
            unanswered.append(category.key)
            per_category[category.key] = 0
            continue
        option = category.option(chosen)
        if option is None:
            unanswered.append(category.key)
            per_category[category.key] = 0
            continue
        if option.blocks_scoring:
            blocked.append(option.blocks_scoring)
        per_category[category.key] = option.score(pattern)

    total = sum(per_category.values())
    calculable = not blocked and pattern != "UNKNOWN"

    reasons = list(blocked)
    if pattern == "UNKNOWN":
        reasons.append(
            "The injury pattern is unknown. The first three categories are scored differently "
            "for hepatocellular versus cholestatic or mixed injury, so ALT and alkaline "
            "phosphatase (with their upper limits of normal) are needed before RUCAM applies."
        )

    return {
        "per_category": per_category,
        "total": total if calculable else None,
        "classification": classify(total) if calculable else None,
        "calculable": calculable,
        "blocking_reasons": reasons,
        "unanswered": unanswered,
        "pattern": pattern,
        "min_possible": MIN_TOTAL,
        "max_possible": MAX_TOTAL,
        "citation": MANUAL_CITATION,
    }
