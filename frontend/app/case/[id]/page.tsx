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
import Rucam from "@/components/steps/Rucam";
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
/** Stages the server runs concurrently in a single request. */
const BATCH_STAGES: SuggestStage[] = [
  "facts",
  "timeline",
  "dimensions",
  "hypotheses",
  "naranjo",
  "who_umc",
];

/** Everything the first open covers, in the order it happens. */
const AUTO_STAGES: SuggestStage[] = [...BATCH_STAGES, "missing"];

const SCREENS: Record<StepId, (p: StepProps) => React.ReactNode> = {
  evidence: EvidenceReview,
  timeline: TimelineEditor,
  investigation: Investigation,
  hypotheses: Hypotheses,
  missing: MissingEvidence,
  naranjo: NaranjoReview,
  rucam: Rucam,
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
  const [auto, setAuto] = useState<{ phase: number; label: string } | null>(null);
  const [autoStalled, setAutoStalled] = useState(false);
  const cancelled = useRef(false);
  const autoStarted = useRef(false);

  /**
   * First-open analysis, in two phases.
   *
   * Phase 1 is a single batched request that the server fans out across the
   * narrative-only stages concurrently — roughly 12s instead of 35s. It is one
   * request on purpose: the per-stage endpoint rewrites the whole document, so
   * calling it six times in parallel from here would discard five of them.
   *
   * Phase 2 runs `missing` afterwards, because it reads reviewer-confirmed
   * evidence and would otherwise be handed an empty case.
   */
  const runAuto = useCallback(
    async (done: string[]) => {
      cancelled.current = false;
      setAutoStalled(false);
      const pending = BATCH_STAGES.filter((s) => !done.includes(s));

      try {
        if (pending.length > 0) {
          setAuto({ phase: 0, label: `Reading the narrative — ${pending.length} passes at once` });
          const res = await api.runSuggestBatch(id, pending);
          setEnvelope(res.envelope);

          const failed = Object.entries(res.failed);
          if (failed.length > 0) {
            setError(
              `${failed.length} step(s) failed: ` +
                failed.map(([s, m]) => `${s} — ${m}`).join("; "),
            );
            setAutoStalled(true);
            return;
          }
        }

        if (!cancelled.current && !done.includes("missing")) {
          setAuto({ phase: 1, label: "Identifying information gaps" });
          const res = await api.runSuggest(id, "missing");
          setEnvelope(res.envelope);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setAutoStalled(true);
      } finally {
        setAuto(null);
      }
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
      {/* Opaque, not translucent. At 90% alpha every panel border scrolling
          underneath bled through as a drifting hairline, and `backdrop-blur`
          smeared it. The height is pinned to an exact 3.5rem so the bottom
          border lands on a whole pixel instead of flickering on a half one,
          and so the sticky columns below can align to it precisely. */}
      <header className="sticky top-0 z-20 h-14 border-b border-ink-700/60 bg-ink-950">
        <div className="mx-auto flex h-full max-w-[1700px] items-center gap-x-4 overflow-hidden px-5">
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
        <aside className="print:hidden xl:sticky xl:top-14 xl:self-start">
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
        <div className="print:hidden xl:sticky xl:top-14 xl:self-start">
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
                  Preparing this case — phase {auto.phase + 1} of 2: {auto.label}…
                </p>
                {auto.phase === 0 && (
                  <Button
                    size="sm"
                    className="ml-auto"
                    onClick={() => {
                      cancelled.current = true;
                    }}
                    title="Let this phase finish, then stop rather than looking for information gaps"
                  >
                    Skip the rest
                  </Button>
                )}
              </div>
              <div
                className="mt-2.5 h-1 overflow-hidden rounded-full bg-ink-800"
                role="progressbar"
                aria-valuenow={auto.phase + 1}
                aria-valuemin={1}
                aria-valuemax={2}
              >
                <div
                  className="h-full rounded-full bg-violet-300 transition-all duration-500"
                  style={{ width: `${((auto.phase + 1) / 2) * 100}%` }}
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

          {/* Interaction is blocked while the first-open run is in flight.
              Every write path reloads, mutates and saves the whole document,
              so a review action landing mid-batch could be overwritten by it.
              There is nothing to review yet during this window anyway. */}
          <div
            className={auto ? "pointer-events-none select-none opacity-60" : undefined}
            aria-busy={Boolean(auto)}
          >
            <Screen
              envelope={envelope}
              run={run}
              suggest={suggest}
              busyKey={auto ? `suggest-${auto.phase === 0 ? "facts" : "missing"}` : busyKey}
              active={active}
              onSelectSpan={setActive}
            />
          </div>

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
