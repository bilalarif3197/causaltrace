import type { AnalysisResult, ExampleCase, HealthInfo } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Error carrying the backend's human-readable detail (e.g. mock-mode limits). */
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
    // The browser deliberately hides the difference between "connection
    // refused" and "blocked by CORS" from JavaScript, so we cannot tell which
    // happened. Naming both beats confidently blaming the wrong one.
    throw new ApiError(
      `Could not complete the request to ${BASE}. Either the API is not running, or the ` +
        `browser blocked the response as cross-origin. ` +
        `Start the API with: cd backend && .venv/bin/uvicorn main:app --reload --port 8000  ` +
        `If it is already running, check the browser console for a CORS error and confirm ` +
        `this page's origin (${typeof window === "undefined" ? "unknown" : window.location.origin}) ` +
        `is allowed by the API.`,
      0,
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const getHealth = () => request<HealthInfo>("/api/health");

export const getExamples = () => request<ExampleCase[]>("/api/examples");

export const analyze = (body: {
  narrative: string;
  suspected_drug: string;
  adverse_event: string;
  case_id?: string | null;
  run_who_umc?: boolean;
}) => request<AnalysisResult>("/api/analyze", { method: "POST", body: JSON.stringify(body) });
