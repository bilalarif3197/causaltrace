"""Naranjo ADR Probability Scale.

Two strictly separated halves:

  1. A deterministic scoring table and `score_items()`. Pure Python, no LLM,
     no network. Given answers, the score and classification are reproducible.
  2. `answer_items()`, which asks the model to answer each item YES/NO/UNKNOWN
     with a supporting quote -- and nothing more. The model never sees or
     produces a total.

Weights and bands are transcribed from the Naranjo worksheet as published in
LiverTox (NCBI Bookshelf NBK548069). Total scores range from -4 to +13:
definite >=9, probable 5-8, possible 1-4, doubtful <=0.

Scoring convention for item 6 (placebo): published case reports essentially
never administer placebo. We answer UNKNOWN (0) rather than NO (+1) when a
placebo challenge is not reported, because scoring it NO silently inflates
every case by a point. This is a documented, conservative choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.models import Answer, NaranjoItem, NaranjoResult, SourceSpan, Verdict


@dataclass(frozen=True)
class ItemSpec:
    number: int
    question: str
    yes: int
    no: int
    unknown: int
    #: Items that are "unknown" >85% of the time in real pharmacovigilance
    #: practice -- and which tend to be the decisive ones.
    commonly_unknown: bool = False
    guidance: str = ""

    def weight(self, answer: Answer) -> int:
        return {Answer.YES: self.yes, Answer.NO: self.no, Answer.UNKNOWN: self.unknown}[answer]


NARANJO_ITEMS: tuple[ItemSpec, ...] = (
    ItemSpec(
        1,
        "Are there previous conclusive reports on this reaction?",
        yes=1,
        no=0,
        unknown=0,
        guidance="YES only if the narrative itself cites prior literature or a known label association.",
    ),
    ItemSpec(
        2,
        "Did the adverse event appear after the suspected drug was administered?",
        yes=2,
        no=-1,
        unknown=0,
        guidance="Requires an explicit temporal sequence in the text.",
    ),
    ItemSpec(
        3,
        "Did the adverse event improve when the drug was discontinued or a specific antagonist was administered?",
        yes=1,
        no=0,
        unknown=0,
        guidance="This is dechallenge. UNKNOWN if the drug was never stopped or the outcome is not reported.",
    ),
    ItemSpec(
        4,
        "Did the adverse event reappear when the drug was readministered?",
        yes=2,
        no=-1,
        unknown=0,
        commonly_unknown=True,
        guidance="This is rechallenge. UNKNOWN unless a readministration is actually described.",
    ),
    ItemSpec(
        5,
        "Are there alternative causes that could on their own have caused the reaction?",
        yes=-1,
        no=2,
        unknown=0,
        guidance=(
            "YES if the narrative documents a competing explanation (infection, another "
            "plausible culprit drug, underlying disease). NO requires positive evidence that "
            "alternatives were considered and excluded -- absence of mention is UNKNOWN, not NO."
        ),
    ),
    ItemSpec(
        6,
        "Did the reaction reappear when a placebo was given?",
        yes=-1,
        no=1,
        unknown=0,
        commonly_unknown=True,
        guidance="UNKNOWN unless a placebo was actually administered. Do not answer NO by default.",
    ),
    ItemSpec(
        7,
        "Was the drug detected in blood or other fluids in concentrations known to be toxic?",
        yes=1,
        no=0,
        unknown=0,
        commonly_unknown=True,
        guidance="Requires a reported drug concentration. UNKNOWN if levels were not measured.",
    ),
    ItemSpec(
        8,
        "Was the reaction more severe when the dose was increased or less severe when the dose was decreased?",
        yes=1,
        no=0,
        unknown=0,
        commonly_unknown=True,
        guidance="UNKNOWN if the dose was never altered or the information is not available.",
    ),
    ItemSpec(
        9,
        "Did the patient have a similar reaction to the same or similar drugs in any previous exposure?",
        yes=1,
        no=0,
        unknown=0,
        guidance="Past medical history of reaction to this drug or a structurally related one.",
    ),
    ItemSpec(
        10,
        "Was the adverse event confirmed by any objective evidence?",
        yes=1,
        no=0,
        unknown=0,
        guidance="Laboratory documentation or direct observation by a qualified clinician.",
    ),
)

ITEMS_BY_NUMBER = {spec.number: spec for spec in NARANJO_ITEMS}

MIN_POSSIBLE = sum(min(s.yes, s.no, s.unknown) for s in NARANJO_ITEMS)  # -4
MAX_POSSIBLE = sum(max(s.yes, s.no, s.unknown) for s in NARANJO_ITEMS)  # +13


def classify(score: int) -> str:
    """Map a total score to its Naranjo band."""
    if score >= 9:
        return "Definite"
    if score >= 5:
        return "Probable"
    if score >= 1:
        return "Possible"
    return "Doubtful"


def score_items(items: list[NaranjoItem]) -> NaranjoResult:
    """Deterministically total a set of answered items.

    Also computes the range the total *could* occupy if every UNKNOWN item were
    resolved either way. When that range spans more than one band, the headline
    classification is not stable and the UI says so -- which is the honest
    reading of a case built on missing data.
    """
    total = 0
    floor = 0
    ceiling = 0
    unknown_count = 0

    for item in items:
        spec = ITEMS_BY_NUMBER[item.number]
        item.score = spec.weight(item.answer)
        item.commonly_unknown = spec.commonly_unknown
        total += item.score
        if item.answer is Answer.UNKNOWN:
            unknown_count += 1
            # If resolved, this item would score either its YES or its NO weight.
            floor += min(spec.yes, spec.no)
            ceiling += max(spec.yes, spec.no)
        else:
            floor += item.score
            ceiling += item.score

    return NaranjoResult(
        items=items,
        total_score=total,
        classification=classify(total),  # type: ignore[arg-type]
        unknown_count=unknown_count,
        score_floor=floor,
        score_ceiling=ceiling,
        classification_is_stable=classify(floor) == classify(ceiling),
    )


# ---------------------------------------------------------------------------
# LLM-facing half: answer the items, never total them
# ---------------------------------------------------------------------------

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "answer": {"type": "string", "enum": ["YES", "NO", "UNKNOWN"]},
                    "rationale": {"type": "string"},
                    "evidence_text": {
                        "type": ["string", "null"],
                        "description": "Verbatim quote from the narrative, or null if UNKNOWN.",
                    },
                },
            },
        }
    },
}

SYSTEM = """You are a pharmacovigilance assessor applying the Naranjo ADR Probability Scale.

You answer each of the 10 items independently with YES, NO, or UNKNOWN.

Absolute rules:
- Answer UNKNOWN whenever the narrative does not state the information. UNKNOWN is a
  correct and valuable answer; guessing is not.
- Absence of evidence is never evidence of absence. If alternative causes are simply
  not discussed, item 5 is UNKNOWN, not NO.
- Every YES or NO must carry a verbatim quote copied character-for-character from the
  narrative. If you cannot quote it, the answer is UNKNOWN with evidence_text null.
- Never compute or mention a total score or a classification. You answer items only."""


def answer_items(client, *, narrative: str, suspected_drug: str, adverse_event: str, case_id: str | None):
    """Ask the model to answer all 10 items, then bind quotes to source spans."""
    from services.spans import locate_span

    question_block = "\n".join(
        f"{s.number}. {s.question}\n   Guidance: {s.guidance}" for s in NARANJO_ITEMS
    )
    user = (
        f"Suspected drug: {suspected_drug}\n"
        f"Adverse event: {adverse_event}\n\n"
        f"NARRATIVE:\n\"\"\"\n{narrative}\n\"\"\"\n\n"
        f"Answer all 10 Naranjo items:\n{question_block}"
    )

    raw = client.complete_json(
        stage="naranjo",
        system=SYSTEM,
        user=user,
        schema=ANSWER_SCHEMA,
        schema_name="naranjo_items",
        case_id=case_id,
    )

    by_number = {int(r["number"]): r for r in raw.get("items", [])}
    results: list[NaranjoItem] = []
    for spec in NARANJO_ITEMS:
        row = by_number.get(spec.number, {})
        answer = Answer(row.get("answer", "UNKNOWN"))
        quote = row.get("evidence_text")
        span: SourceSpan | None = locate_span(narrative, quote)

        # A YES/NO whose citation is not in the source text is demoted to
        # UNKNOWN. An ungrounded answer must not move the score.
        verdict: Verdict | None = None
        if answer is not Answer.UNKNOWN:
            if span is None or not span.located:
                answer = Answer.UNKNOWN
                verdict = Verdict.NOT_SUPPORTED
                quote = None
                span = None
            else:
                verdict = Verdict.SUPPORTED

        results.append(
            NaranjoItem(
                number=spec.number,
                question=spec.question,
                answer=answer,
                rationale=row.get("rationale", ""),
                evidence_text=quote,
                span=span,
                verdict=verdict,
                commonly_unknown=spec.commonly_unknown,
            )
        )
    return results
