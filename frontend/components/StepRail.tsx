"use client";

import type { CaseEnvelope } from "@/lib/review";
import { CheckIcon } from "./ui";

export const STEPS = [
  { id: "evidence", label: "Evidence review", short: "Evidence" },
  { id: "timeline", label: "Clinical timeline", short: "Timeline" },
  { id: "investigation", label: "Investigation", short: "Investigation" },
  { id: "hypotheses", label: "Competing causes", short: "Causes" },
  { id: "missing", label: "Missing evidence", short: "Gaps" },
  { id: "naranjo", label: "Naranjo framework", short: "Naranjo" },
  { id: "rucam", label: "RUCAM (liver)", short: "RUCAM" },
  { id: "whoumc", label: "WHO-UMC", short: "WHO-UMC" },
  { id: "conclusion", label: "Reviewer conclusion", short: "Conclusion" },
  { id: "report", label: "Case report", short: "Report" },
] as const;

export type StepId = (typeof STEPS)[number]["id"];

/** Outstanding-work count per step, so the rail shows where attention is owed. */
function pending(env: CaseEnvelope, step: StepId): number {
  const s = env.stats;
  switch (step) {
    case "evidence":
      return s.facts_pending;
    case "timeline":
      return s.timeline_pending;
    case "investigation":
      return s.dimensions_pending;
    case "hypotheses":
      return Math.max(0, s.hypotheses_total - s.hypotheses_assessed);
    case "missing":
      return s.missing_open;
    case "naranjo":
      return s.naranjo_pending;
    case "rucam": {
      // Not applicable to non-hepatic events, so nothing is owed.
      const r = env.case.rucam;
      if (!r || !r.applicable) return 0;
      return r.answers.filter((a) => !a.reviewer_status.startsWith("REVIEWER")).length;
    }
    case "whoumc":
      return env.case.who_umc && !env.case.who_umc.reviewer_classification ? 1 : 0;
    case "conclusion":
      return env.case.conclusion.final_assessment ? 0 : 1;
    default:
      return 0;
  }
}

function started(env: CaseEnvelope, step: StepId): boolean {
  const c = env.case;
  switch (step) {
    case "evidence":
      return c.facts.length > 0;
    case "timeline":
      return c.timeline.length > 0;
    case "investigation":
      return c.dimensions.length > 0;
    case "hypotheses":
      return c.hypotheses.length > 0;
    case "missing":
      return c.missing_evidence.length > 0;
    case "naranjo":
      return c.naranjo.some((i) => i.ai_answer !== null || i.reviewer_status.startsWith("REVIEWER"));
    case "rucam":
      return !c.rucam?.applicable || c.rucam.answers.some((a) => a.reviewer_status.startsWith("REVIEWER"));
    case "whoumc":
      return c.who_umc !== null;
    case "conclusion":
      return Boolean(c.conclusion.final_assessment);
    case "report":
      return c.conclusion.signed_off;
  }
}

export default function StepRail({
  envelope,
  current,
  onSelect,
}: {
  envelope: CaseEnvelope;
  current: StepId;
  onSelect: (id: StepId) => void;
}) {
  return (
    <nav aria-label="Review steps" className="space-y-1">
      {STEPS.map((step, i) => {
        const isCurrent = step.id === current;
        const count = pending(envelope, step.id);
        const done = started(envelope, step.id) && count === 0;
        return (
          <button
            key={step.id}
            type="button"
            onClick={() => onSelect(step.id)}
            aria-current={isCurrent ? "step" : undefined}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition ${
              isCurrent
                ? "bg-accent-500/12 text-accent-400 ring-1 ring-accent-500/40"
                : "text-slate-muted hover:bg-ink-800/60 hover:text-slate-soft"
            }`}
          >
            <span
              className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px] font-semibold ${
                done
                  ? "border-support-400/50 bg-support-bg text-support-400"
                  : isCurrent
                    ? "border-accent-500/60 text-accent-400"
                    : "border-ink-600 text-slate-muted"
              }`}
              aria-hidden
            >
              {done ? <CheckIcon className="h-3 w-3" /> : i + 1}
            </span>
            <span className="flex-1 truncate text-[12.5px] font-medium">{step.label}</span>
            {count > 0 && (
              <span
                className="shrink-0 rounded-full border border-unknown-400/40 bg-unknown-bg px-1.5 py-px font-mono text-[10px] text-unknown-400"
                title={`${count} item(s) awaiting your review`}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
