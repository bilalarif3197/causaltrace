"use client";

import { useState } from "react";
import type { ExampleCase } from "@/lib/types";
import { Disclaimer, Panel, Pill } from "./ui";

export default function CaseInput({
  examples,
  mode,
  busy,
  error,
  onAnalyze,
}: {
  examples: ExampleCase[];
  mode: "live" | "mock" | null;
  busy: boolean;
  error: string | null;
  onAnalyze: (input: {
    narrative: string;
    suspected_drug: string;
    adverse_event: string;
    case_id: string | null;
  }) => void;
}) {
  const [narrative, setNarrative] = useState("");
  const [drug, setDrug] = useState("");
  const [event, setEvent] = useState("");
  // Tracks which built-in case is loaded. Mock mode can only replay recorded
  // cases, so we must send the id rather than guess from the text.
  const [caseId, setCaseId] = useState<string | null>(null);

  const loadExample = (ex: ExampleCase) => {
    setNarrative(ex.narrative);
    setDrug(ex.suspected_drug);
    setEvent(ex.adverse_event);
    setCaseId(ex.case_id);
  };

  const ready = narrative.trim() && drug.trim() && event.trim() && !busy;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5">
      <Panel
        title="Case input"
        subtitle="Paste a published adverse drug event case narrative, or load an example."
        aside={
          mode === "mock" ? (
            <Pill tone="unknown" className="shrink-0">
              offline demo mode
            </Pill>
          ) : mode === "live" ? (
            <Pill tone="accent" className="shrink-0">
              live model
            </Pill>
          ) : undefined
        }
      >
        {examples.length > 0 && (
          <div className="mb-5">
            <p className="mb-2 text-[11px] uppercase tracking-wider text-slate-muted">
              Example cases
            </p>
            <div className="grid gap-2.5 sm:grid-cols-3">
              {examples.map((ex) => (
                <button
                  key={ex.case_id}
                  type="button"
                  onClick={() => loadExample(ex)}
                  className={`rounded-lg border px-3.5 py-3 text-left transition ${
                    caseId === ex.case_id
                      ? "border-accent-500/70 bg-accent-500/10"
                      : "border-ink-700 bg-ink-850/60 hover:border-ink-600 hover:bg-ink-800/70"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[12.5px] font-medium leading-snug text-slate-soft">
                      {ex.title}
                    </p>
                    {ex.is_ambiguous && (
                      <span
                        className="mt-0.5 shrink-0 rounded-full border border-unknown-400/40 bg-unknown-bg px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-unknown-400"
                        title="Intentionally ambiguous case"
                      >
                        ambiguous
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-slate-muted">
                    {ex.description}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

        <label className="block">
          <span className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-muted">
            Case narrative
          </span>
          <textarea
            value={narrative}
            onChange={(e) => {
              setNarrative(e.target.value);
              setCaseId(null);
            }}
            rows={12}
            placeholder="A 58-year-old man with type 2 diabetes was started on…"
            className="w-full resize-y rounded-lg border border-ink-700 bg-ink-950/70 px-3.5 py-3 font-mono text-[12.5px] leading-relaxed text-slate-soft placeholder:text-ink-500 focus:border-accent-600 focus:outline-none focus:ring-1 focus:ring-accent-600/40"
          />
        </label>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-muted">
              Suspected drug
            </span>
            <input
              value={drug}
              onChange={(e) => setDrug(e.target.value)}
              placeholder="Drug A"
              className="w-full rounded-lg border border-ink-700 bg-ink-950/70 px-3.5 py-2.5 text-[13px] text-slate-soft placeholder:text-ink-500 focus:border-accent-600 focus:outline-none focus:ring-1 focus:ring-accent-600/40"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-muted">
              Adverse event
            </span>
            <input
              value={event}
              onChange={(e) => setEvent(e.target.value)}
              placeholder="Acute liver injury"
              className="w-full rounded-lg border border-ink-700 bg-ink-950/70 px-3.5 py-2.5 text-[13px] text-slate-soft placeholder:text-ink-500 focus:border-accent-600 focus:outline-none focus:ring-1 focus:ring-accent-600/40"
            />
          </label>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-against-400/40 bg-against-bg px-4 py-3">
            <p className="text-[12.5px] leading-relaxed text-against-400">{error}</p>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button
            type="button"
            disabled={!ready}
            onClick={() =>
              onAnalyze({
                narrative: narrative.trim(),
                suspected_drug: drug.trim(),
                adverse_event: event.trim(),
                case_id: caseId,
              })
            }
            className="inline-flex items-center gap-2.5 rounded-lg bg-accent-500 px-5 py-2.5 text-[13px] font-semibold text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-slate-muted"
          >
            {busy && (
              <span
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-950/30 border-t-ink-950"
                aria-hidden
              />
            )}
            {busy ? "Analyzing…" : "Analyze causality"}
          </button>
          {mode === "mock" && (
            <p className="text-[11px] leading-relaxed text-slate-muted">
              No API key detected — only the example cases above can be analyzed. Set{" "}
              <code className="font-mono text-accent-400/80">OPENAI_API_KEY</code> to analyze your
              own narrative.
            </p>
          )}
        </div>
      </Panel>

      <Disclaimer className="px-1" />
    </div>
  );
}
