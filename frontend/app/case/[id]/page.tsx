"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import * as api from "@/lib/api";
import type { SuggestStage } from "@/lib/api";
import type { ActiveSpan, CaseEnvelope } from "@/lib/review";
import StepRail, { STEPS, type StepId } from "@/components/StepRail";
import { SourcePanel } from "@/components/review";
import { Button, Callout, Disclaimer, Pill } from "@/components/ui";
import EvidenceReview from "@/components/steps/EvidenceReview";
import TimelineEditor from "@/components/steps/TimelineEditor";
import Investigation from "@/components/steps/Investigation";
import Hypotheses from "@/components/steps/Hypotheses";
import MissingEvidence from "@/components/steps/MissingEvidence";
import NaranjoReview from "@/components/steps/NaranjoReview";
import WhoUmc from "@/components/steps/WhoUmc";
import Conclusion from "@/components/steps/Conclusion";
import Report from "@/components/steps/Report";
import type { StepProps } from "@/components/steps/types";

/**
 * Stages run automatically the first time a case is opened.
 *
 * `rationale` is deliberately excluded. It drafts from reviewer-confirmed
 * evidence and pre-fills the conclusion field, so running it before the
 * reviewer has confirmed anything would put machine text into the human's
 * conclusion — the precise failure this product exists to avoid. The reviewer
 * triggers it from the Conclusion step once they have something to say.
 *
 * `missing` is included, but it reads better after review: re-running it later
 * lets it see what the reviewer actually confirmed.
 */
const AUTO_STAGES: { stage: SuggestStage; label: string }[] = [
  { stage: "facts", label: "Extracting evidence" },
  { stage: "timeline", label: "Building the timeline" },
  { stage: "dimensions", label: "Analysing causality dimensions" },
  { stage: "hypotheses", label: "Finding competing causes" },
  { stage: "naranjo", label: "Answering Naranjo items" },
  { stage: "missing", label: "Identifying information gaps" },
  { stage: "who_umc", label: "Drafting a WHO-UMC view" },
];

const SCREENS: Record<StepId, (p: StepProps) => React.ReactNode> = {
  evidence: EvidenceReview,
  timeline: TimelineEditor,
  investigation: Investigation,
  hypotheses: Hypotheses,
  missing: MissingEvidence,
  naranjo: NaranjoReview,
  whoumc: WhoUmc,
  conclusion: Conclusion,
  report: Report,
};

export default function CaseWorkspace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [envelope, setEnvelope] = useState<CaseEnvelope | null>(null);
  const [step, setStep] = useState<StepId>("evidence");
  const [active, setActive] = useState<ActiveSpan | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  /** Progress of the first-open analysis, or null when not running. */
  const [auto, setAuto] = useState<{ index: number; label: string } | null>(null);
  const [autoStalled, setAutoStalled] = useState(false);
  const cancelled = useRef(false);
  const autoStarted = useRef(false);

  /** Run the remaining first-open stages, one at a time so progress is visible. */
  const runAuto = useCallback(
    async (from: string[]) => {
      cancelled.current = false;
      setAutoStalled(false);
      const todo = AUTO_STAGES.filter((s) => !from.includes(s.stage));

      for (let i = 0; i < todo.length; i++) {
        if (cancelled.current) break;
        setAuto({ index: AUTO_STAGES.length - todo.length + i, label: todo[i].label });
        try {
          const res = await api.runSuggest(id, todo[i].stage);
          setEnvelope(res.envelope);
        } catch (e) {
          // Stop rather than firing six more failing calls. The reviewer can
          // resume, or just use the per-step buttons.
          setError(e instanceof Error ? e.message : String(e));
          setAutoStalled(true);
          break;
        }
      }
      setAuto(null);
    },
    [id],
  );

  useEffect(() => {
    api
      .getCase(id)
      .then((env) => {
        setEnvelope(env);
        // First open only: an empty `stages_run` means nothing has been
        // suggested yet. It is persisted, so a refresh will not re-trigger.
        if (env.case.stages_run.length === 0 && !autoStarted.current) {
          autoStarted.current = true;
          void runAuto([]);
        }
      })
      .catch((e) => setError(e.message));
  }, [id, runAuto]);

  /** Run a mutation, fold the new envelope in, and surface failures. */
  const run = useCallback(
    async (key: string, fn: () => Promise<CaseEnvelope>) => {
      setBusyKey(key);
      setError(null);
      try {
        setEnvelope(await fn());
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyKey(null);
      }
    },
    [],
  );

  const suggest = useCallback(
    async (stage: SuggestStage) => {
      setBusyKey(`suggest-${stage}`);
      setError(null);
      setNote(null);
      try {
        const res = await api.runSuggest(id, stage);
        setEnvelope(res.envelope);
        setNote(res.note);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyKey(null);
      }
    },
    [id],
  );

  if (error && !envelope) {
    return (
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <Callout tone="against" title="Could not load this case">
          {error}
        </Callout>
        <div className="mt-4">
          <Link href="/" className="text-[13px] text-accent-400 underline underline-offset-2">
            ← Back to cases
          </Link>
        </div>
      </main>
    );
  }

  if (!envelope) {
    return (
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <p className="text-[13px] text-slate-muted">Loading case…</p>
      </main>
    );
  }

  const doc = envelope.case;
  const Screen = SCREENS[step];
  const stepIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <main className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-700/60 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1700px] flex-wrap items-center gap-x-4 gap-y-2 px-5 py-2.5">
          <Link
            href="/"
            className="text-[12px] text-slate-muted transition hover:text-accent-400"
          >
            ← Cases
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-[14px] font-semibold tracking-tight text-slate-soft">
              {doc.suspected_drug} → {doc.adverse_event}
            </h1>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {envelope.framework && (
              <Pill
                tone="neutral"
                title="Computed from your reviewed answers only"
                className="font-mono"
              >
                Naranjo{" "}
                {envelope.framework.total_score > 0
                  ? `+${envelope.framework.total_score}`
                  : envelope.framework.total_score}{" "}
                · {envelope.framework.classification}
              </Pill>
            )}
            {doc.conclusion.final_assessment ? (
              <Pill tone="accent">Reviewer: {doc.conclusion.final_assessment}</Pill>
            ) : (
              <Pill tone="unknown">no reviewer conclusion yet</Pill>
            )}
            <Pill tone={doc.mode === "live" ? "accent" : "unknown"}>{doc.mode}</Pill>
          </div>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-[1700px] flex-1 gap-5 px-5 py-5 print:block print:max-w-none print:p-0 xl:grid-cols-[13rem_minmax(0,1.15fr)_minmax(0,1.5fr)]">
        {/* Step rail */}
        <aside className="print:hidden xl:sticky xl:top-[3.75rem] xl:self-start">
          <StepRail envelope={envelope} current={step} onSelect={setStep} />
          <div className="mt-4 rounded-lg border border-ink-700/60 bg-ink-900/50 px-3 py-2.5">
            <p className="text-[10px] uppercase tracking-wider text-slate-muted">Review progress</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-slate-soft">
              {envelope.stats.facts_accepted + envelope.stats.facts_modified} of{" "}
              {envelope.stats.facts_total} facts confirmed
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-soft">
              {envelope.stats.naranjo_reviewed}/10 Naranjo items answered
            </p>
          </div>
        </aside>

        {/* Source narrative stays visible: it is what makes every pane auditable. */}
        <div className="print:hidden xl:sticky xl:top-[3.75rem] xl:self-start">
          <SourcePanel narrative={doc.narrative} active={active} onClear={() => setActive(null)} />
        </div>

        {/* Active step */}
        <div className="min-w-0 space-y-4">
          {auto && (
            <section className="rounded-xl border border-violet-400/40 bg-violet-400/10 px-4 py-3.5">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-300/30 border-t-violet-300"
                  aria-hidden
                />
                <p className="text-[12.5px] font-medium text-slate-soft">
                  Preparing this case — step {auto.index + 1} of {AUTO_STAGES.length}:{" "}
                  {auto.label}…
                </p>
                <Button
                  size="sm"
                  className="ml-auto"
                  onClick={() => {
                    cancelled.current = true;
                  }}
                  title="Stop here and run the remaining steps yourself"
                >
                  Skip the rest
                </Button>
              </div>
              <div
                className="mt-2.5 h-1 overflow-hidden rounded-full bg-ink-800"
                role="progressbar"
                aria-valuenow={auto.index + 1}
                aria-valuemin={1}
                aria-valuemax={AUTO_STAGES.length}
              >
                <div
                  className="h-full rounded-full bg-violet-300 transition-all duration-500"
                  style={{ width: `${((auto.index + 1) / AUTO_STAGES.length) * 100}%` }}
                />
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-muted">
                This runs once, on first open. Everything arrives as a suggestion for you to
                accept, edit or reject — nothing is added to the assessment until you say so.
              </p>
            </section>
          )}

          {autoStalled && !auto && (
            <Callout tone="unknown" title="First-open analysis stopped early">
              Some steps did not complete. You can resume, or just run whichever steps you need
              from their own buttons.
              <div className="mt-2.5">
                <Button
                  size="sm"
                  onClick={() => void runAuto(envelope.case.stages_run)}
                  busy={Boolean(auto)}
                >
                  Resume analysis
                </Button>
              </div>
            </Callout>
          )}

          {note && !auto && (
            <Callout tone="ai" title="AI suggestion run complete">
              {note}. Nothing has been added to your assessment — review each item below.
            </Callout>
          )}
          {error && !auto && (
            <Callout tone="against" title="Problem">
              {error}
            </Callout>
          )}

          {/* While the first-open run is in flight, every control reports busy
              so the reviewer cannot fire a second suggestion on top of it. */}
          <Screen
            envelope={envelope}
            run={run}
            suggest={suggest}
            busyKey={auto ? `suggest-${AUTO_STAGES[auto.index]?.stage ?? "facts"}` : busyKey}
            active={active}
            onSelectSpan={setActive}
          />

          <nav className="flex items-center justify-between gap-3 border-t border-ink-700/60 pt-4">
            <Button
              size="sm"
              disabled={stepIndex <= 0}
              onClick={() => setStep(STEPS[Math.max(0, stepIndex - 1)].id)}
            >
              ← {stepIndex > 0 ? STEPS[stepIndex - 1].short : "Back"}
            </Button>
            <span className="text-[11px] text-slate-muted">
              Step {stepIndex + 1} of {STEPS.length}
            </span>
            <Button
              size="sm"
              tone="primary"
              disabled={stepIndex >= STEPS.length - 1}
              onClick={() => setStep(STEPS[Math.min(STEPS.length - 1, stepIndex + 1)].id)}
            >
              {stepIndex < STEPS.length - 1 ? STEPS[stepIndex + 1].short : "Done"} →
            </Button>
          </nav>

          <Disclaimer className="pt-2" />
        </div>
      </div>
    </main>
  );
}
