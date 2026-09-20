import type {
  AuditEntry,
  CaseEnvelope,
  CaseSummary,
  DemoCase,
  HealthInfo,
  ReviewerStatus,
} from "./review";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    // The browser hides the difference between connection-refused and
    // CORS-blocked from JavaScript, so name both rather than guess wrong.
    throw new ApiError(
      `Could not reach the CausalTrace API at ${BASE}. Either it is not running, or the ` +
        `browser blocked the response as cross-origin. Start it with: ` +
        `cd backend && .venv/bin/uvicorn main:app --reload --port 8000`,
      0,
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail))
        detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

/* -------------------------------------------------------------------------- */

export const getHealth = () => request<HealthInfo>("/api/health");
export const getDemoCases = () => request<DemoCase[]>("/api/demo-cases");
export const listCases = () => request<CaseSummary[]>("/api/cases");
export const getCase = (id: string) => request<CaseEnvelope>(`/api/cases/${id}`);
export const deleteCase = (id: string) =>
  request<void>(`/api/cases/${id}`, { method: "DELETE" });

export const createCase = (body: {
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  title?: string;
  indication?: string | null;
  age?: string | null;
  sex?: string | null;
  concomitant_medications?: string | null;
  comorbidities?: string | null;
  demo_case_id?: string | null;
}) => post<CaseEnvelope>("/api/cases", body);

export type SuggestStage =
  | "facts"
  | "timeline"
  | "dimensions"
  | "hypotheses"
  | "missing"
  | "naranjo"
  | "who_umc"
  | "rucam"
  | "rationale";

export const runSuggest = (id: string, stage: SuggestStage) =>
  post<{ envelope: CaseEnvelope; note: string; stage: string }>(
    `/api/cases/${id}/suggest/${stage}`,
  );

/**
 * Run the narrative-only stages concurrently, server-side.
 *
 * Must not be emulated by firing the single-stage endpoint several times from
 * here: each of those rewrites the whole case document, so parallel calls
 * would let the last response win and discard the rest.
 */
export const runSuggestBatch = (id: string, stages?: SuggestStage[]) =>
  post<{
    envelope: CaseEnvelope;
    notes: string[];
    stages: string[];
    failed: Record<string, string>;
  }>(`/api/cases/${id}/suggest-batch`, { stages: stages ?? null });

export interface RucamCategory {
  key: string;
  number: number;
  title: string;
  question: string;
  note: string;
  options: {
    key: string;
    label: string;
    points: Record<string, number>;
    blocks_scoring: string | null;
  }[];
}

/** Served by the backend so the UI never duplicates the weight table. */
export const getRucamCategories = () => request<RucamCategory[]>("/api/rucam-categories");

export const setRucamLabs = (
  id: string,
  body: { alt?: number | null; alt_uln?: number | null; alp?: number | null; alp_uln?: number | null },
) =>
  request<CaseEnvelope>(`/api/cases/${id}/rucam-labs`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

/** Retrieve the FDA label as citable evidence for Naranjo item 1. */
export const lookupLabel = (id: string) =>
  post<{ envelope: CaseEnvelope; note: string; stage: string }>(
    `/api/cases/${id}/label-lookup`,
  );

export const reviewEntity = (
  id: string,
  entityType: string,
  entityId: string,
  body: {
    status?: ReviewerStatus;
    value?: string | null;
    note?: string | null;
    extra?: Record<string, unknown>;
  },
) =>
  request<CaseEnvelope>(`/api/cases/${id}/review/${entityType}/${entityId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const bulkReview = (
  id: string,
  body: { entity_type: string; status: ReviewerStatus; section?: string | null },
) => post<CaseEnvelope>(`/api/cases/${id}/review/bulk`, body);

export const addFact = (id: string, body: { field: string; value: string; note?: string }) =>
  post<CaseEnvelope>(`/api/cases/${id}/facts`, body);

export const addEvent = (
  id: string,
  body: {
    label: string;
    order_index?: number;
    date_kind?: string;
    display_date?: string | null;
    relative_text?: string | null;
    category?: string;
    actor?: string | null;
  },
) => post<CaseEnvelope>(`/api/cases/${id}/events`, body);

export const deleteEvent = (id: string, eventId: string) =>
  request<CaseEnvelope>(`/api/cases/${id}/events/${eventId}`, { method: "DELETE" });

export const addHypothesis = (id: string, body: { label: string; kind?: string }) =>
  post<CaseEnvelope>(`/api/cases/${id}/hypotheses`, body);

export const addMissing = (id: string, body: { prompt: string; why_it_matters?: string }) =>
  post<CaseEnvelope>(`/api/cases/${id}/missing`, body);

export const setConclusion = (
  id: string,
  body: {
    final_assessment?: string | null;
    primary_cause_hypothesis_id?: string | null;
    reviewer_rationale?: string | null;
    signed_off?: boolean;
  },
) =>
  request<CaseEnvelope>(`/api/cases/${id}/conclusion`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const getAudit = (id: string) => request<AuditEntry[]>(`/api/cases/${id}/audit`);
