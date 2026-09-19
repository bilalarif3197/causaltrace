"use client";

import { useCallback, useEffect, useState } from "react";
import CaseInput from "@/components/CaseInput";
import CausalGraph from "@/components/CausalGraph";
import ClaimsPanel from "@/components/ClaimsPanel";
import EvidencePanel from "@/components/EvidencePanel";
import HypothesisPanel from "@/components/HypothesisPanel";
import NaranjoTable from "@/components/NaranjoTable";
import Timeline from "@/components/Timeline";
import WhoUmcPanel from "@/components/WhoUmcPanel";
import { Disclaimer, Panel, Pill } from "@/components/ui";
import { analyze, getExamples, getHealth } from "@/lib/api";
import type { ActiveSpan, AnalysisResult, ExampleCase } from "@/lib/types";

type Tab = "hypotheses" | "timeline" | "naranjo" | "who" | "evidence";

const TABS: { id: Tab; label: string }[] = [
  { id: "hypotheses", label: "Competing causes" },
  { id: "timeline", label: "Timeline" },
  { id: "naranjo", label: "Naranjo" },
  { id: "who", label: "WHO-UMC" },
  { id: "evidence", label: "Extracted evidence" },
];

export default function Home() {
  const [examples, setExamples] = useState<ExampleCase[]>([]);
  const [mode, setMode] = useState<"live" | "mock" | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>("hypotheses");
  const [active, setActive] = useState<ActiveSpan | null>(null);
  const [selectedHypothesis, setSelectedHypothesis] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then((h) => setMode(h.mode))
      .catch(() => setMode(null));
    getExamples()
      .then(setExamples)
      .catch((e) => setError(e.message));
  }, []);

  const runAnalysis = useCallback(
    async (input: {
      narrative: string;
      suspected_drug: string;
      adverse_event: string;
      case_id: string | null;
    }) => {
      setBusy(true);
      setError(null);
      try {
        const res = await analyze(input);
        setResult(res);
        setMode(res.mode);
        setActive(null);
        setTab("hypotheses");
        // Default to the suspected-drug hypothesis so the graph opens on
        // something meaningful rather than empty.
        setSelectedHypothesis(
          res.hypotheses.find((h) => h.kind === "SUSPECT_DRUG")?.id ?? res.hypotheses[0]?.id ?? null,
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const reset = () => {
    setResult(null);
    setActive(null);
    setError(null);
  };

  const hypothesis = result?.hypotheses.find((h) => h.id === selectedHypothesis) ?? null;

  return (
    <main className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-700/60 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-5 py-3">
          <button type="button" onClick={reset} className="flex items-center gap-2.5 text-left">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-accent-500/15 ring-1 ring-accent-500/40">
              <svg viewBox="0 0 20 20" className="h-4 w-4 text-accent-400" fill="currentColor" aria-hidden>
                <path d="M3 10.5a1 1 0 0 1 1-1h2.3l1.7-4.2a1 1 0 0 1 1.88.06l2.3 7.1 1.2-2.75a1 1 0 0 1 .92-.6H17a1 1 0 0 1 0 2h-1.35l-1.83 4.2a1 1 0 0 1-1.87-.09l-2.3-7.08-1.2 2.76a1 1 0 0 1-.92.6H4a1 1 0 0 1-1-1Z" />
              </svg>
            </span>
            <span>
              <span className="block text-[15px] font-semibold leading-none tracking-tight text-slate-soft">
                CausalTrace
              </span>
              <span className="mt-0.5 block text-[10px] uppercase tracking-[0.14em] text-slate-muted">
                evidence-grounded ADR causality
              </span>
            </span>
          </button>

          <div className="ml-auto flex items-center gap-2.5">
            {mode && <Pill tone={mode === "live" ? "accent" : "unknown"}>{mode} mode</Pill>}
            {result && (
              <button
                type="button"
                onClick={reset}
                className="rounded-lg border border-ink-600 px-3 py-1.5 text-[12px] text-slate-soft transition hover:border-accent-600/60 hover:text-accent-400"
              >
                New case
              </button>
            )}
          </div>
        </div>
      </header>

      {!result ? (
        <div className="flex-1 px-5 py-10">
          <div className="mx-auto mb-9 max-w-4xl text-center">
            <h1 className="text-balance text-2xl font-semibold tracking-tight text-slate-soft sm:text-3xl">
              Did the drug cause it?
            </h1>
            <p className="mx-auto mt-3 max-w-2xl text-pretty text-[13.5px] leading-relaxed text-slate-muted">
              CausalTrace reads a published adverse drug event narrative and produces a structured,
              auditable causality assessment — competing explanations, an evidence trail back to the
              source text, and an explicit account of what could not be determined.
            </p>
          </div>
          <CaseInput
            examples={examples}
            mode={mode}
            busy={busy}
            error={error}
            onAnalyze={runAnalysis}
          />
        </div>
      ) : (
        <div className="mx-auto w-full max-w-[1600px] flex-1 px-5 py-6">
          {/* Case header */}
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="text-lg font-semibold tracking-tight text-slate-soft">
                  {result.suspected_drug} → {result.adverse_event}
                </h1>
                <Pill tone="neutral" className="font-mono">
                  {result.case_id}
                </Pill>
              </div>
              <p className="mt-1 text-[11px] text-slate-muted">
                {result.claims.length} claims · {result.timeline.length} timeline events ·{" "}
                {result.hypotheses.length} hypotheses · {result.elapsed_seconds}s
                {result.model ? ` · ${result.model}` : ""}
              </p>
            </div>

            <div className="flex items-stretch gap-3">
              <div className="rounded-lg border border-ink-700 bg-ink-900/70 px-4 py-2 text-center">
                <p className="font-mono text-xl font-semibold leading-none text-accent-400">
                  {result.naranjo.total_score > 0
                    ? `+${result.naranjo.total_score}`
                    : result.naranjo.total_score}
                </p>
                <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-muted">
                  Naranjo · {result.naranjo.classification}
                </p>
              </div>
              <div className="rounded-lg border border-ink-700 bg-ink-900/70 px-4 py-2 text-center">
                <p className="font-mono text-xl font-semibold leading-none text-unknown-400">
                  {result.naranjo.unknown_count}/10
                </p>
                <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-muted">
                  items unknown
                </p>
              </div>
            </div>
          </div>

          {result.warnings.length > 0 && (
            <div className="mb-5 rounded-xl border border-unknown-400/30 bg-unknown-bg px-4 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-unknown-400">
                What this assessment cannot tell you
              </h2>
              <ul className="mt-2 space-y-1.5">
                {result.warnings.map((w, i) => (
                  <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-slate-soft">
                    <span className="text-unknown-400" aria-hidden>
                      •
                    </span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
            {/* Evidence inspector stays visible: it is what makes every other
                pane auditable. */}
            <div className="xl:sticky xl:top-[4.75rem] xl:self-start">
              <EvidencePanel
                narrative={result.narrative}
                active={active}
                onClear={() => setActive(null)}
              />
            </div>

            <div className="space-y-5">
              <nav className="flex flex-wrap gap-1.5 rounded-xl border border-ink-700/70 bg-ink-900/60 p-1.5">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTab(t.id)}
                    aria-current={tab === t.id}
                    className={`rounded-lg px-3.5 py-1.5 text-[12px] font-medium transition ${
                      tab === t.id
                        ? "bg-accent-500/15 text-accent-400 ring-1 ring-accent-500/40"
                        : "text-slate-muted hover:bg-ink-800/70 hover:text-slate-soft"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </nav>

              {tab === "hypotheses" && (
                <>
                  <CausalGraph
                    hypotheses={result.hypotheses}
                    adverseEvent={result.adverse_event}
                    selectedId={selectedHypothesis}
                    onSelect={setSelectedHypothesis}
                  />
                  <HypothesisPanel hypothesis={hypothesis} active={active} onSelect={setActive} />
                </>
              )}

              {tab === "timeline" && (
                <Timeline events={result.timeline} active={active} onSelect={setActive} />
              )}

              {tab === "naranjo" && (
                <NaranjoTable result={result.naranjo} active={active} onSelect={setActive} />
              )}

              {tab === "who" &&
                (result.who_umc ? (
                  <WhoUmcPanel result={result.who_umc} active={active} onSelect={setActive} />
                ) : (
                  <Panel title="WHO-UMC assessment">
                    <p className="text-sm text-slate-muted">
                      WHO-UMC assessment was not run for this case.
                    </p>
                  </Panel>
                ))}

              {tab === "evidence" && (
                <ClaimsPanel result={result} active={active} onSelect={setActive} />
              )}
            </div>
          </div>

          <footer className="mt-8 border-t border-ink-700/60 pt-4">
            <Disclaimer />
          </footer>
        </div>
      )}
    </main>
  );
}
