"""Pydantic schemas shared across every CausalTrace pipeline stage.

Design rules encoded here:
  * A claim without a locatable source span is never treated as SUPPORTED.
  * Missing information is represented explicitly as UNKNOWN, never imputed.
  * Causal strength is a qualitative label; no fabricated numeric probabilities.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimStatus(str, Enum):
    """Whether a claim is grounded in the narrative or simply not reported."""

    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"


class Verdict(str, Enum):
    """Result of the Stage 4 verification pass over a claim's cited evidence."""

    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class Answer(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class SupportLabel(str, Enum):
    """Qualitative strength labels. Deliberately not probabilities."""

    STRONG = "Strong support"
    MODERATE = "Moderate support"
    LIMITED = "Limited support"
    INSUFFICIENT = "Insufficient evidence"


class DateCertainty(str, Enum):
    EXACT = "EXACT"
    RELATIVE = "RELATIVE"
    UNKNOWN = "UNKNOWN"


class EventCategory(str, Enum):
    DRUG_START = "DRUG_START"
    DRUG_STOP = "DRUG_STOP"
    DOSE_CHANGE = "DOSE_CHANGE"
    EVENT_ONSET = "EVENT_ONSET"
    LAB = "LAB"
    INFECTION = "INFECTION"
    DIAGNOSIS = "DIAGNOSIS"
    RECHALLENGE = "RECHALLENGE"
    RECOVERY = "RECOVERY"
    OTHER = "OTHER"


class HypothesisKind(str, Enum):
    SUSPECT_DRUG = "SUSPECT_DRUG"
    CONCOMITANT_DRUG = "CONCOMITANT_DRUG"
    INFECTION = "INFECTION"
    UNDERLYING_DISEASE = "UNDERLYING_DISEASE"
    INTERACTION = "INTERACTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Evidence grounding
# ---------------------------------------------------------------------------


class SourceSpan(BaseModel):
    """A span of the original narrative, resolved to character offsets.

    `start`/`end` are None when the quoted text could not be located in the
    narrative -- which we treat as a hallucination signal, not a rendering
    detail.
    """

    text: str
    start: Optional[int] = None
    end: Optional[int] = None
    locator: Literal["exact", "normalized", "fuzzy", "unlocatable"] = "unlocatable"
    match_ratio: float = 0.0

    @property
    def located(self) -> bool:
        return self.start is not None and self.end is not None


class Claim(BaseModel):
    """One extracted clinical fact, grounded in a source span.

    The `claim` / `value` / `evidence_text` / `confidence` / `status` quintet is
    the contract the extraction prompt must satisfy; everything else is added by
    the pipeline.
    """

    id: str
    slot: str = Field(description="Which extraction slot this fills, e.g. 'dechallenge'.")
    claim: str
    value: Optional[str] = None
    evidence_text: Optional[str] = None
    confidence: float = 0.0
    status: ClaimStatus = ClaimStatus.UNKNOWN

    span: Optional[SourceSpan] = None
    verdict: Optional[Verdict] = None
    verdict_reason: Optional[str] = None
    dropped: bool = False
    drop_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 2 -- timeline
# ---------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    id: str
    label: str
    category: EventCategory = EventCategory.OTHER
    order: int = Field(description="Relative ordering index; always populated.")
    date: Optional[str] = Field(default=None, description="ISO-8601 date if stated.")
    display_date: Optional[str] = Field(default=None, description="e.g. 'Jan 03' or 'Day 14'.")
    relative_text: Optional[str] = Field(default=None, description="e.g. 'two weeks later'.")
    date_certainty: DateCertainty = DateCertainty.UNKNOWN
    actor: Optional[str] = Field(default=None, description="Drug or entity the event concerns.")
    span: Optional[SourceSpan] = None


# ---------------------------------------------------------------------------
# Stage 3 -- competing hypotheses
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single bullet of evidence attached to a hypothesis."""

    id: str
    statement: str
    evidence_text: Optional[str] = None
    span: Optional[SourceSpan] = None
    verdict: Optional[Verdict] = None


class Hypothesis(BaseModel):
    id: str
    hypothesis: str
    kind: HypothesisKind = HypothesisKind.CONCOMITANT_DRUG
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    unknown_evidence: list[EvidenceItem] = Field(default_factory=list)
    support_label: SupportLabel = SupportLabel.INSUFFICIENT
    label_rationale: str = ""


# ---------------------------------------------------------------------------
# Naranjo
# ---------------------------------------------------------------------------


class NaranjoItem(BaseModel):
    number: int
    question: str
    answer: Answer = Answer.UNKNOWN
    score: int = 0
    rationale: str = ""
    evidence_text: Optional[str] = None
    span: Optional[SourceSpan] = None
    verdict: Optional[Verdict] = None
    verdict_reason: Optional[str] = None
    commonly_unknown: bool = Field(
        default=False,
        description="True for the items answered 'unknown' >85% of the time in practice.",
    )


class NaranjoResult(BaseModel):
    items: list[NaranjoItem]
    total_score: int
    classification: Literal["Definite", "Probable", "Possible", "Doubtful"]
    unknown_count: int
    # Bounds the score could take if every UNKNOWN were resolved. Makes the
    # "missing data" problem legible instead of hiding it behind a point score.
    score_floor: int
    score_ceiling: int
    classification_is_stable: bool = Field(
        description="True when floor and ceiling fall in the same classification band."
    )


# ---------------------------------------------------------------------------
# WHO-UMC
# ---------------------------------------------------------------------------


class WhoUmcCriterion(BaseModel):
    criterion: str
    met: Answer = Answer.UNKNOWN
    note: str = ""


class WhoUmcResult(BaseModel):
    classification: Literal[
        "Certain",
        "Probable",
        "Possible",
        "Unlikely",
        "Conditional/Unclassified",
        "Unassessable/Unclassifiable",
    ]
    reasoning: str
    criteria: list[WhoUmcCriterion] = Field(default_factory=list)
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    major_uncertainty: str = ""


# ---------------------------------------------------------------------------
# Verification + envelope
# ---------------------------------------------------------------------------


class VerificationSummary(BaseModel):
    total_claims: int = 0
    supported: int = 0
    not_supported: int = 0
    ambiguous: int = 0
    unlocatable_spans: int = 0
    dropped: int = 0

    @property
    def unsupported_assertion_rate(self) -> float:
        if not self.total_claims:
            return 0.0
        return (self.not_supported + self.unlocatable_spans) / self.total_claims


class AnalyzeRequest(BaseModel):
    narrative: str = Field(min_length=1)
    suspected_drug: str = Field(min_length=1)
    adverse_event: str = Field(min_length=1)
    case_id: Optional[str] = None
    run_who_umc: bool = True


class AnalysisResult(BaseModel):
    case_id: str
    narrative: str
    suspected_drug: str
    adverse_event: str

    claims: list[Claim] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    naranjo: NaranjoResult
    who_umc: Optional[WhoUmcResult] = None

    verification: VerificationSummary = Field(default_factory=VerificationSummary)
    unsupported_assertion_rate: float = 0.0
    mode: Literal["live", "mock"] = "mock"
    model: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0


class ExampleCase(BaseModel):
    case_id: str
    title: str
    description: str
    narrative: str
    suspected_drug: str
    adverse_event: str
    is_ambiguous: bool = False
