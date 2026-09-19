"use client";

import { use, useCallback, useEffect, useState } from "react";
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

  useEffect(() => {
    api
      .getCase(id)
      .then(setEnvelope)
      .catch((e) => setError(e.message));
  }, [id]);

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
          {note && (
            <Callout tone="ai" title="AI suggestion run complete">
              {note}. Nothing has been added to your assessment — review each item below.
            </Callout>
          )}
          {error && (
            <Callout tone="against" title="Problem">
              {error}
            </Callout>
          )}

          <Screen
            envelope={envelope}
            run={run}
            suggest={suggest}
            busyKey={busyKey}
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
