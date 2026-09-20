/** Mirrors backend/schemas/review.py. Keep in sync. */

export type ReviewerStatus =
  | "AI_SUGGESTED"
  | "REVIEWER_ACCEPTED"
  | "REVIEWER_MODIFIED"
  | "REVIEWER_REJECTED"
  | "UNKNOWN"
  | "NEEDS_REVIEW";

export type Origin = "AI" | "REVIEWER";
export type Verdict = "SUPPORTED" | "PARTIALLY_SUPPORTED" | "NOT_SUPPORTED";
export type Answer = "YES" | "NO" | "UNKNOWN";
export type DateKind = "EXACT" | "APPROXIMATE" | "RELATIVE" | "UNKNOWN";

export type FactSection =
  | "DRUG_EXPOSURE"
  | "ADVERSE_EVENT"
  | "OTHER_EXPOSURES"
  | "MEDICAL_CONTEXT";

export type DimensionName =
  | "TEMPORALITY"
  | "DECHALLENGE"
  | "RECHALLENGE"
  | "DOSE_RELATIONSHIP"
  | "ALTERNATIVE_ETIOLOGIES";

export type AssessmentLevel =
  | "Strongly supported"
  | "Moderately supported"
  | "Weakly supported"
  | "Not supported"
  | "Insufficient evidence";

export type MissingStatus =
  | "OPEN"
  | "OBTAINABLE"
  | "UNAVAILABLE"
  | "NOT_RELEVANT"
  | "ADDED_TO_CASE";

export type EvidenceValence = "SUPPORTING" | "CONTRADICTING" | "UNKNOWN";

export type CaseStage =
  | "INTAKE"
  | "EVIDENCE"
  | "TIMELINE"
  | "INVESTIGATION"
  | "HYPOTHESES"
  | "MISSING"
  | "NARANJO"
  | "WHO_UMC"
  | "CONCLUSION"
  | "REPORT";

export interface SourceSpan {
  text: string;
  start: number | null;
  end: number | null;
  locator: "exact" | "normalized" | "fuzzy" | "unlocatable";
  match_ratio: number;
}

export interface AiSuggestion {
  value: string | null;
  rationale: string;
  evidence_text: string | null;
  span: SourceSpan | null;
  confidence: number;
  verification: Verdict | null;
  verification_reason: string | null;
  suggested_at: string;
}

/** Fields shared by every reviewable entity. */
export interface ReviewableBase {
  ai: AiSuggestion | null;
  reviewer_status: ReviewerStatus;
  reviewer_value: string | null;
  reviewer_note: string | null;
  origin: Origin;
  reviewed_at: string | null;
}

export interface Fact extends ReviewableBase {
  id: string;
  section: FactSection;
  field: string;
  label: string;
}

export interface TimelineEntry extends ReviewableBase {
  id: string;
  label: string;
  category: string;
  order_index: number;
  date_kind: DateKind;
  date_value: string | null;
  display_date: string | null;
  relative_text: string | null;
  actor: string | null;
  timing_uncertain: boolean;
}

export interface DimensionQuestion extends ReviewableBase {
  id: string;
  dimension: DimensionName;
  key: string;
  question: string;
}

export interface HypothesisEvidence extends ReviewableBase {
  id: string;
  valence: EvidenceValence;
  statement: string;
}

export interface Hypothesis {
  id: string;
  label: string;
  kind: string;
  is_suspected_drug: boolean;
  ai_assessment: AssessmentLevel | null;
  ai_rationale: string;
  reviewer_assessment: AssessmentLevel | null;
  reviewer_status: ReviewerStatus;
  reviewer_note: string | null;
  origin: Origin;
  evidence: HypothesisEvidence[];
  reviewed_at: string | null;
}

export interface MissingEvidenceItem {
  id: string;
  prompt: string;
  why_it_matters: string;
  affects: string[];
  status: MissingStatus;
  reviewer_note: string | null;
  origin: Origin;
  reviewed_at: string | null;
}

export interface NaranjoReviewItem {
  number: number;
  question: string;
  ai: AiSuggestion | null;
  ai_answer: Answer | null;
  reviewer_answer: Answer;
  reviewer_status: ReviewerStatus;
  reviewer_note: string | null;
  score: number;
  commonly_unknown: boolean;
  reviewed_at: string | null;
}

export interface FrameworkResult {
  total_score: number;
  classification: "Definite" | "Probable" | "Possible" | "Doubtful";
  unknown_count: number;
  unreviewed_count: number;
  score_floor: number;
  score_ceiling: number;
  classification_is_stable: boolean;
}

export interface LabelEvidence {
  queried_drug: string;
  adverse_event: string;
  label_found: boolean;
  /** null means undetermined. false means "not on this label", never "no prior reports". */
  mentions_event: boolean | null;
  quote: string | null;
  span: SourceSpan | null;
  section: string | null;
  reasoning: string;
  label_text: string;
  sections_included: string;
  citation: {
    label_id?: string | null;
    set_id?: string | null;
    effective_time?: string | null;
    matched_by?: string | null;
    brand_names?: string[];
    generic_names?: string[];
    manufacturer?: string | null;
    url?: string | null;
  };
  unavailable_reason: string | null;
  fetched_at: string;
  CAVEAT: string;
}

export interface WhoUmcReview {
  ai_classification: string | null;
  ai_reasoning: string;
  ai_major_uncertainty: string;
  reviewer_classification: string | null;
  reviewer_status: ReviewerStatus;
  reviewer_note: string | null;
  key_evidence: HypothesisEvidence[];
  reviewed_at: string | null;
}

export interface RucamAnswer {
  category: string;
  title: string;
  ai_answer: string | null;
  ai: AiSuggestion | null;
  reviewer_answer: string | null;
  reviewer_status: ReviewerStatus;
  reviewer_note: string | null;
  score: number;
  reviewed_at: string | null;
}

export interface RucamAssessment {
  applicable: boolean;
  not_applicable_reason: string | null;
  labs: { alt: number | null; alt_uln: number | null; alp: number | null; alp_uln: number | null };
  r_ratio: number | null;
  pattern: "HEPATOCELLULAR" | "CHOLESTATIC" | "MIXED" | "UNKNOWN";
  answers: RucamAnswer[];
  /** null when the manual says a RUCAM must not be produced. */
  total: number | null;
  classification: string | null;
  calculable: boolean;
  blocking_reasons: string[];
  unanswered: string[];
  citation: string;
}

export interface Conclusion {
  final_assessment: string | null;
  primary_cause_hypothesis_id: string | null;
  ai_draft_rationale: string;
  reviewer_rationale: string;
  rationale_status: ReviewerStatus;
  signed_off: boolean;
  decided_at: string | null;
}

export interface PatientContext {
  indication: string | null;
  age: string | null;
  sex: string | null;
  concomitant_medications: string | null;
  comorbidities: string | null;
}

export interface CaseDocument {
  id: string;
  created_at: string;
  updated_at: string;
  title: string;
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  patient: PatientContext;
  demo_case_id: string | null;
  facts: Fact[];
  timeline: TimelineEntry[];
  dimensions: DimensionQuestion[];
  hypotheses: Hypothesis[];
  missing_evidence: MissingEvidenceItem[];
  naranjo: NaranjoReviewItem[];
  who_umc: WhoUmcReview | null;
  label_evidence: LabelEvidence | null;
  rucam: RucamAssessment | null;
  conclusion: Conclusion;
  stages_run: string[];
  model_used: string | null;
  mode: string;
}

export interface ReviewStats {
  facts_total: number;
  facts_accepted: number;
  facts_modified: number;
  facts_rejected: number;
  facts_pending: number;
  facts_unsupported: number;
  timeline_total: number;
  timeline_pending: number;
  hypotheses_total: number;
  hypotheses_assessed: number;
  hypotheses_retained: number;
  dimensions_total: number;
  dimensions_pending: number;
  missing_total: number;
  missing_open: number;
  naranjo_reviewed: number;
  naranjo_pending: number;
  ai_suggestions_total: number;
  reviewer_corrections: number;
}

export interface CaseEnvelope {
  case: CaseDocument;
  stats: ReviewStats;
  framework: FrameworkResult | null;
  stage: CaseStage;
  disclaimer: string;
}

export interface CaseSummary {
  id: string;
  title: string;
  suspected_drug: string;
  adverse_event: string;
  created_at: string;
  updated_at: string;
  stage: CaseStage;
  final_assessment: string | null;
  signed_off: boolean;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: Origin;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface DemoCase {
  case_id: string;
  title: string;
  description: string;
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  is_ambiguous: boolean;
  indication: string | null;
  age: string | null;
  sex: string | null;
  concomitant_medications: string | null;
  comorbidities: string | null;
}

export interface HealthInfo {
  status: string;
  mode: "live" | "mock";
  model: string;
  disclaimer: string;
  json_mode: string | null;
  notes: string[];
  mock_cases: string[];
  who_umc_categories: string[];
}

/** The span currently highlighted in the source panel. */
export interface ActiveSpan {
  span: SourceSpan;
  sourceId: string;
  label?: string;
}

/* --------------------------------------------------------------------------
   Display helpers
   -------------------------------------------------------------------------- */

export type IconName = "ai" | "check" | "pencil" | "cross" | "question" | "warn" | "dot";

export const STATUS_META: Record<
  ReviewerStatus,
  { icon: IconName; label: string; tone: string; ring: string }
> = {
  AI_SUGGESTED: {
    icon: "ai",
    label: "AI suggested",
    tone: "text-violet-300",
    ring: "border-violet-400/40 bg-violet-400/10",
  },
  REVIEWER_ACCEPTED: {
    icon: "check",
    label: "Reviewer confirmed",
    tone: "text-support-400",
    ring: "border-support-400/40 bg-support-bg",
  },
  REVIEWER_MODIFIED: {
    icon: "pencil",
    label: "Reviewer modified",
    tone: "text-accent-400",
    ring: "border-accent-500/40 bg-accent-500/10",
  },
  REVIEWER_REJECTED: {
    icon: "cross",
    label: "Reviewer rejected",
    tone: "text-against-400",
    ring: "border-against-400/40 bg-against-bg",
  },
  UNKNOWN: {
    icon: "question",
    label: "Unknown",
    tone: "text-slate-muted",
    ring: "border-ink-600 bg-ink-800/70",
  },
  NEEDS_REVIEW: {
    icon: "warn",
    label: "Needs review",
    tone: "text-unknown-400",
    ring: "border-unknown-400/50 bg-unknown-bg",
  },
};

export const SECTION_LABELS: Record<FactSection, string> = {
  DRUG_EXPOSURE: "Drug exposure",
  ADVERSE_EVENT: "Adverse event",
  OTHER_EXPOSURES: "Other exposures",
  MEDICAL_CONTEXT: "Medical context",
};

export const DIMENSION_LABELS: Record<DimensionName, string> = {
  TEMPORALITY: "Temporality",
  DECHALLENGE: "Dechallenge",
  RECHALLENGE: "Rechallenge",
  DOSE_RELATIONSHIP: "Dose relationship",
  ALTERNATIVE_ETIOLOGIES: "Alternative etiologies",
};

export const ASSESSMENT_LEVELS: AssessmentLevel[] = [
  "Strongly supported",
  "Moderately supported",
  "Weakly supported",
  "Not supported",
  "Insufficient evidence",
];

export const MISSING_STATUSES: { value: MissingStatus; label: string }[] = [
  { value: "OPEN", label: "Open" },
  { value: "OBTAINABLE", label: "Obtainable" },
  { value: "UNAVAILABLE", label: "Unavailable" },
  { value: "NOT_RELEVANT", label: "Not relevant" },
  { value: "ADDED_TO_CASE", label: "Added to case" },
];

/** Value a reviewable currently contributes downstream, or null. */
export function confirmedValue(item: ReviewableBase): string | null {
  if (item.reviewer_status === "REVIEWER_MODIFIED") return item.reviewer_value;
  if (item.reviewer_status === "REVIEWER_ACCEPTED") {
    return item.reviewer_value ?? item.ai?.value ?? null;
  }
  return null;
}

export function isPending(status: ReviewerStatus): boolean {
  return status === "AI_SUGGESTED" || status === "NEEDS_REVIEW";
}
