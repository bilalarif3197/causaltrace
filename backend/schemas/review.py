"""The reviewer-centred data model.

The single most important rule in this file: **an AI suggestion is never
mutated by a reviewer decision.** Every reviewable entity carries two parallel
slots -- `ai` (immutable once written) and the reviewer's verdict -- so that
the audit trail can always answer "what did the machine propose, what did the
human do about it, and why".

The second rule follows from the first: `confirmed_value` is the *only* thing
downstream assessment is allowed to read. An AI suggestion nobody has looked at
yet is not evidence, and it contributes nothing to a Naranjo score or a
conclusion. That is what makes this a review workspace rather than a
prediction engine with a confirmation dialog bolted on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .models import SourceSpan


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Review state
# ---------------------------------------------------------------------------


class ReviewerStatus(str, Enum):
    AI_SUGGESTED = "AI_SUGGESTED"
    ACCEPTED = "REVIEWER_ACCEPTED"
    MODIFIED = "REVIEWER_MODIFIED"
    REJECTED = "REVIEWER_REJECTED"
    UNKNOWN = "UNKNOWN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


#: Statuses whose value is allowed to flow into downstream assessment.
CONFIRMED_STATUSES = {ReviewerStatus.ACCEPTED, ReviewerStatus.MODIFIED}


class Origin(str, Enum):
    AI = "AI"
    REVIEWER = "REVIEWER"


class Verdict(str, Enum):
    """Result of the evidence-verification pass."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class AiSuggestion(BaseModel):
    """What the model proposed. Write once; never edited by reviewer actions."""

    value: Optional[str] = None
    rationale: str = ""
    evidence_text: Optional[str] = None
    span: Optional[SourceSpan] = None
    confidence: float = 0.0
    verification: Optional[Verdict] = None
    verification_reason: Optional[str] = None
    suggested_at: str = Field(default_factory=utcnow)

    @property
    def grounded(self) -> bool:
        """A suggestion is grounded only if its quote was located in the source."""
        return bool(self.span and self.span.start is not None)


class Reviewable(BaseModel):
    """Mixin carrying the AI/reviewer split."""

    ai: Optional[AiSuggestion] = None
    reviewer_status: ReviewerStatus = ReviewerStatus.AI_SUGGESTED
    reviewer_value: Optional[str] = None
    reviewer_note: Optional[str] = None
    origin: Origin = Origin.AI
    reviewed_at: Optional[str] = None

    @property
    def confirmed_value(self) -> Optional[str]:
        """The value downstream assessment may use -- and nothing else.

        Deliberately returns None for AI_SUGGESTED: an unreviewed suggestion is
        a proposal, not a fact. Returning the AI value here would quietly turn
        this back into an autonomous system.
        """
        if self.reviewer_status not in CONFIRMED_STATUSES:
            return None
        if self.reviewer_status is ReviewerStatus.MODIFIED:
            return self.reviewer_value
        # ACCEPTED: the reviewer may still have supplied a value explicitly.
        if self.reviewer_value is not None:
            return self.reviewer_value
        return self.ai.value if self.ai else None

    @property
    def is_confirmed(self) -> bool:
        return self.reviewer_status in CONFIRMED_STATUSES

    @property
    def needs_attention(self) -> bool:
        """Unreviewed, or verified as unsupported and therefore suspect."""
        if self.reviewer_status is ReviewerStatus.NEEDS_REVIEW:
            return True
        if self.reviewer_status is not ReviewerStatus.AI_SUGGESTED:
            return False
        return True

    def apply_review(
        self,
        status: ReviewerStatus,
        value: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        """Record a reviewer decision without touching `self.ai`."""
        self.reviewer_status = status
        if status is ReviewerStatus.MODIFIED:
            self.reviewer_value = value
        elif status is ReviewerStatus.ACCEPTED:
            self.reviewer_value = value if value is not None else None
        elif status in (ReviewerStatus.REJECTED, ReviewerStatus.UNKNOWN):
            self.reviewer_value = None
        if note is not None:
            self.reviewer_note = note
        self.reviewed_at = utcnow()


# ---------------------------------------------------------------------------
# Screen 2 -- extracted facts
# ---------------------------------------------------------------------------


class FactSection(str, Enum):
    DRUG_EXPOSURE = "DRUG_EXPOSURE"
    ADVERSE_EVENT = "ADVERSE_EVENT"
    OTHER_EXPOSURES = "OTHER_EXPOSURES"
    MEDICAL_CONTEXT = "MEDICAL_CONTEXT"


SECTION_FIELDS: dict[FactSection, list[tuple[str, str]]] = {
    FactSection.DRUG_EXPOSURE: [
        ("suspected_drug", "Suspected drug"),
        ("dose", "Dose"),
        ("route", "Route"),
        ("start_date", "Start date"),
        ("stop_date", "Stop date"),
        ("duration", "Duration"),
        ("dose_changes", "Dose changes"),
    ],
    FactSection.ADVERSE_EVENT: [
        ("event", "Adverse event"),
        ("onset_date", "Onset date"),
        ("severity", "Severity"),
        ("symptoms", "Relevant symptoms"),
        ("objective_tests", "Objective tests"),
        ("lab_abnormalities", "Lab abnormalities"),
    ],
    FactSection.OTHER_EXPOSURES: [
        ("concomitant_medications", "Concomitant medication"),
        ("recently_stopped_medications", "Recently stopped medication"),
        ("alcohol", "Alcohol"),
        ("supplements", "Supplements"),
        ("recreational_drugs", "Recreational drugs"),
        ("infections", "Infection"),
    ],
    FactSection.MEDICAL_CONTEXT: [
        ("comorbidities", "Comorbidity"),
        ("previous_similar_events", "Previous similar event"),
        ("baseline_labs", "Baseline labs"),
        ("relevant_diagnoses", "Relevant diagnosis"),
    ],
}

ALL_FIELD_KEYS = [key for fields in SECTION_FIELDS.values() for key, _ in fields]


class Fact(Reviewable):
    id: str
    section: FactSection
    field: str
    label: str


# ---------------------------------------------------------------------------
# Screen 3 -- timeline
# ---------------------------------------------------------------------------


class DateKind(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    RELATIVE = "RELATIVE"
    UNKNOWN = "UNKNOWN"


class TimelineEntry(Reviewable):
    id: str
    label: str
    category: str = "OTHER"
    order_index: int = 0
    date_kind: DateKind = DateKind.UNKNOWN
    date_value: Optional[str] = None
    display_date: Optional[str] = None
    relative_text: Optional[str] = None
    actor: Optional[str] = None
    timing_uncertain: bool = False


# ---------------------------------------------------------------------------
# Screen 4 -- causality investigation dimensions
# ---------------------------------------------------------------------------


class Dimension(str, Enum):
    TEMPORALITY = "TEMPORALITY"
    DECHALLENGE = "DECHALLENGE"
    RECHALLENGE = "RECHALLENGE"
    DOSE_RELATIONSHIP = "DOSE_RELATIONSHIP"
    ALTERNATIVE_ETIOLOGIES = "ALTERNATIVE_ETIOLOGIES"


DIMENSION_QUESTIONS: dict[Dimension, list[tuple[str, str]]] = {
    Dimension.TEMPORALITY: [
        ("exposure_before_event", "Did exposure occur before the event?"),
        ("latency_plausible", "Is the latency biologically plausible?"),
        ("during_or_after", "Did the event occur during treatment or after treatment?"),
        ("consistent_with_knowledge", "Is the timing consistent with previous knowledge?"),
    ],
    Dimension.DECHALLENGE: [
        ("drug_stopped", "Was the suspected drug stopped?"),
        ("improved_after_stopping", "Did the adverse event improve after stopping?"),
        ("other_intervention", "Could improvement be explained by another intervention?"),
    ],
    Dimension.RECHALLENGE: [
        ("drug_restarted", "Was the drug restarted?"),
        ("event_recurred", "Did the event recur?"),
        ("deliberately_avoided", "Was rechallenge intentionally avoided?"),
    ],
    Dimension.DOSE_RELATIONSHIP: [
        ("worse_with_increase", "Did the event worsen with increased dose?"),
        ("better_with_reduction", "Did it improve with dose reduction?"),
        ("dose_available", "Is dose information available?"),
    ],
}


class DimensionQuestion(Reviewable):
    id: str
    dimension: Dimension
    key: str
    question: str


# ---------------------------------------------------------------------------
# Screens 4/5 -- alternative causes and competing hypotheses
# ---------------------------------------------------------------------------


class EvidenceValence(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    UNKNOWN = "UNKNOWN"


class HypothesisEvidence(Reviewable):
    id: str
    valence: EvidenceValence
    statement: str


class AssessmentLevel(str, Enum):
    STRONGLY_SUPPORTED = "Strongly supported"
    MODERATELY_SUPPORTED = "Moderately supported"
    WEAKLY_SUPPORTED = "Weakly supported"
    NOT_SUPPORTED = "Not supported"
    INSUFFICIENT = "Insufficient evidence"


class Hypothesis(BaseModel):
    """A candidate explanation. The reviewer's assessment is authoritative; the
    AI's is retained beside it and never overwrites it."""

    id: str
    label: str
    kind: str = "OTHER"
    is_suspected_drug: bool = False
    ai_assessment: Optional[AssessmentLevel] = None
    ai_rationale: str = ""
    reviewer_assessment: Optional[AssessmentLevel] = None
    reviewer_status: ReviewerStatus = ReviewerStatus.AI_SUGGESTED
    reviewer_note: Optional[str] = None
    origin: Origin = Origin.AI
    evidence: list[HypothesisEvidence] = Field(default_factory=list)
    reviewed_at: Optional[str] = None

    @property
    def effective_assessment(self) -> Optional[AssessmentLevel]:
        """Reviewer wins. No fallback to the AI value -- an unreviewed
        hypothesis has no assessment, and the UI must say so."""
        return self.reviewer_assessment

    def bucket(self, valence: EvidenceValence) -> list[HypothesisEvidence]:
        return [e for e in self.evidence if e.valence is valence]


# ---------------------------------------------------------------------------
# Screen 6 -- missing evidence
# ---------------------------------------------------------------------------


class MissingEvidenceStatus(str, Enum):
    OPEN = "OPEN"
    OBTAINABLE = "OBTAINABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_RELEVANT = "NOT_RELEVANT"
    ADDED = "ADDED_TO_CASE"


class MissingEvidenceItem(BaseModel):
    id: str
    prompt: str
    why_it_matters: str = ""
    affects: list[str] = Field(default_factory=list)
    status: MissingEvidenceStatus = MissingEvidenceStatus.OPEN
    reviewer_note: Optional[str] = None
    origin: Origin = Origin.AI
    reviewed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Screen 7 -- Naranjo
# ---------------------------------------------------------------------------


class Answer(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class NaranjoReviewItem(BaseModel):
    """One Naranjo item with AI suggestion and reviewer answer held separately.

    `score` is always derived from `reviewer_answer` -- never from the AI's.
    """

    number: int
    question: str
    ai: Optional[AiSuggestion] = None
    ai_answer: Optional[Answer] = None
    reviewer_answer: Answer = Answer.UNKNOWN
    reviewer_status: ReviewerStatus = ReviewerStatus.AI_SUGGESTED
    reviewer_note: Optional[str] = None
    score: int = 0
    commonly_unknown: bool = False
    reviewed_at: Optional[str] = None


class FrameworkResult(BaseModel):
    """Deliberately named 'framework result', not 'final decision'."""

    total_score: int
    classification: Literal["Definite", "Probable", "Possible", "Doubtful"]
    unknown_count: int
    unreviewed_count: int
    score_floor: int
    score_ceiling: int
    classification_is_stable: bool


# ---------------------------------------------------------------------------
# Screen 8 -- WHO-UMC
# ---------------------------------------------------------------------------

WHO_UMC_CATEGORIES = [
    "Certain",
    "Probable",
    "Possible",
    "Unlikely",
    "Conditional/Unclassified",
    "Unassessable/Unclassifiable",
]


class WhoUmcReview(BaseModel):
    ai_classification: Optional[str] = None
    ai_reasoning: str = ""
    ai_major_uncertainty: str = ""
    reviewer_classification: Optional[str] = None
    reviewer_status: ReviewerStatus = ReviewerStatus.AI_SUGGESTED
    reviewer_note: Optional[str] = None
    key_evidence: list[HypothesisEvidence] = Field(default_factory=list)
    reviewed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Screen 9 -- reviewer conclusion
# ---------------------------------------------------------------------------


class Conclusion(BaseModel):
    final_assessment: Optional[str] = None
    primary_cause_hypothesis_id: Optional[str] = None
    ai_draft_rationale: str = ""
    reviewer_rationale: str = ""
    rationale_status: ReviewerStatus = ReviewerStatus.AI_SUGGESTED
    signed_off: bool = False
    decided_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: int = 0
    at: str = Field(default_factory=utcnow)
    actor: Origin
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    summary: str = ""
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# The case document
# ---------------------------------------------------------------------------


class CaseStage(str, Enum):
    INTAKE = "INTAKE"
    EVIDENCE = "EVIDENCE"
    TIMELINE = "TIMELINE"
    INVESTIGATION = "INVESTIGATION"
    HYPOTHESES = "HYPOTHESES"
    MISSING = "MISSING"
    NARANJO = "NARANJO"
    WHO_UMC = "WHO_UMC"
    CONCLUSION = "CONCLUSION"
    REPORT = "REPORT"


class PatientContext(BaseModel):
    indication: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    concomitant_medications: Optional[str] = None
    comorbidities: Optional[str] = None


class CaseDocument(BaseModel):
    id: str
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)

    title: str = ""
    narrative: str
    suspected_drug: str
    adverse_event: str
    patient: PatientContext = Field(default_factory=PatientContext)
    demo_case_id: Optional[str] = None

    facts: list[Fact] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    dimensions: list[DimensionQuestion] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    missing_evidence: list[MissingEvidenceItem] = Field(default_factory=list)
    naranjo: list[NaranjoReviewItem] = Field(default_factory=list)
    who_umc: Optional[WhoUmcReview] = None
    conclusion: Conclusion = Field(default_factory=Conclusion)

    #: Which suggest steps have been run, so the UI can prompt correctly.
    stages_run: list[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    mode: str = "mock"

    def find_fact(self, fact_id: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.id == fact_id), None)

    def find_event(self, event_id: str) -> Optional[TimelineEntry]:
        return next((e for e in self.timeline if e.id == event_id), None)

    def find_dimension(self, qid: str) -> Optional[DimensionQuestion]:
        return next((d for d in self.dimensions if d.id == qid), None)

    def find_hypothesis(self, hid: str) -> Optional[Hypothesis]:
        return next((h for h in self.hypotheses if h.id == hid), None)

    def find_missing(self, mid: str) -> Optional[MissingEvidenceItem]:
        return next((m for m in self.missing_evidence if m.id == mid), None)

    def find_hypothesis_evidence(self, eid: str) -> Optional[HypothesisEvidence]:
        for hypothesis in self.hypotheses:
            for item in hypothesis.evidence:
                if item.id == eid:
                    return item
        return None


class ReviewStats(BaseModel):
    """Counts driving the progress rail and the AI-assistance audit."""

    facts_total: int = 0
    facts_accepted: int = 0
    facts_modified: int = 0
    facts_rejected: int = 0
    facts_pending: int = 0
    facts_unsupported: int = 0
    timeline_total: int = 0
    timeline_pending: int = 0
    hypotheses_total: int = 0
    hypotheses_assessed: int = 0
    hypotheses_retained: int = 0
    dimensions_total: int = 0
    dimensions_pending: int = 0
    missing_total: int = 0
    missing_open: int = 0
    naranjo_reviewed: int = 0
    naranjo_pending: int = 0
    ai_suggestions_total: int = 0
    reviewer_corrections: int = 0

    @property
    def correction_rate(self) -> float:
        if not self.ai_suggestions_total:
            return 0.0
        return round(self.reviewer_corrections / self.ai_suggestions_total, 4)


class CaseSummary(BaseModel):
    id: str
    title: str
    suspected_drug: str
    adverse_event: str
    created_at: str
    updated_at: str
    stage: CaseStage
    final_assessment: Optional[str] = None
    signed_off: bool = False


class CaseEnvelope(BaseModel):
    """What the API returns: the document plus everything derived from it."""

    case: CaseDocument
    stats: ReviewStats
    framework: Optional[FrameworkResult] = None
    stage: CaseStage = CaseStage.INTAKE
    disclaimer: str = ""
