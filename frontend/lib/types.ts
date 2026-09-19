/** Mirrors backend/schemas/models.py. Keep in sync. */

export type ClaimStatus = "SUPPORTED" | "UNKNOWN";
export type Verdict = "SUPPORTED" | "NOT_SUPPORTED" | "AMBIGUOUS";
export type Answer = "YES" | "NO" | "UNKNOWN";
export type DateCertainty = "EXACT" | "RELATIVE" | "UNKNOWN";

export type SupportLabel =
  | "Strong support"
  | "Moderate support"
  | "Limited support"
  | "Insufficient evidence";

export type EventCategory =
  | "DRUG_START"
  | "DRUG_STOP"
  | "DOSE_CHANGE"
  | "EVENT_ONSET"
  | "LAB"
  | "INFECTION"
  | "DIAGNOSIS"
  | "RECHALLENGE"
  | "RECOVERY"
  | "OTHER";

export type HypothesisKind =
  | "SUSPECT_DRUG"
  | "CONCOMITANT_DRUG"
  | "INFECTION"
  | "UNDERLYING_DISEASE"
  | "INTERACTION"
  | "INSUFFICIENT_EVIDENCE";

export interface SourceSpan {
  text: string;
  start: number | null;
  end: number | null;
  locator: "exact" | "normalized" | "fuzzy" | "unlocatable";
  match_ratio: number;
}

export interface Claim {
  id: string;
  slot: string;
  claim: string;
  value: string | null;
  evidence_text: string | null;
  confidence: number;
  status: ClaimStatus;
  span: SourceSpan | null;
  verdict: Verdict | null;
  verdict_reason: string | null;
  dropped: boolean;
  drop_reason: string | null;
}

export interface TimelineEvent {
  id: string;
  label: string;
  category: EventCategory;
  order: number;
  date: string | null;
  display_date: string | null;
  relative_text: string | null;
  date_certainty: DateCertainty;
  actor: string | null;
  span: SourceSpan | null;
}

export interface EvidenceItem {
  id: string;
  statement: string;
  evidence_text: string | null;
  span: SourceSpan | null;
  verdict: Verdict | null;
}

export interface Hypothesis {
  id: string;
  hypothesis: string;
  kind: HypothesisKind;
  supporting_evidence: EvidenceItem[];
  contradicting_evidence: EvidenceItem[];
  unknown_evidence: EvidenceItem[];
  support_label: SupportLabel;
  label_rationale: string;
}

export interface NaranjoItem {
  number: number;
  question: string;
  answer: Answer;
  score: number;
  rationale: string;
  evidence_text: string | null;
  span: SourceSpan | null;
  verdict: Verdict | null;
  commonly_unknown: boolean;
}

export interface NaranjoResult {
  items: NaranjoItem[];
  total_score: number;
  classification: "Definite" | "Probable" | "Possible" | "Doubtful";
  unknown_count: number;
  score_floor: number;
  score_ceiling: number;
  classification_is_stable: boolean;
}

export interface WhoUmcCriterion {
  criterion: string;
  met: Answer;
  note: string;
}

export interface WhoUmcResult {
  classification: string;
  reasoning: string;
  criteria: WhoUmcCriterion[];
  supporting_evidence: EvidenceItem[];
  major_uncertainty: string;
}

export interface VerificationSummary {
  total_claims: number;
  supported: number;
  not_supported: number;
  ambiguous: number;
  unlocatable_spans: number;
  dropped: number;
}

export interface AnalysisResult {
  case_id: string;
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  claims: Claim[];
  timeline: TimelineEvent[];
  hypotheses: Hypothesis[];
  naranjo: NaranjoResult;
  who_umc: WhoUmcResult | null;
  verification: VerificationSummary;
  unsupported_assertion_rate: number;
  mode: "live" | "mock";
  model: string | null;
  warnings: string[];
  elapsed_seconds: number;
}

export interface ExampleCase {
  case_id: string;
  title: string;
  description: string;
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  is_ambiguous: boolean;
}

export interface HealthInfo {
  status: string;
  mode: "live" | "mock";
  model: string;
  disclaimer: string;
  mock_cases: string[];
}

/** The span currently highlighted in the narrative panel. */
export interface ActiveSpan {
  span: SourceSpan;
  /** Where the selection came from, so that pane can show its own selection state. */
  sourceId: string;
  label?: string;
}
