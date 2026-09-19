"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";
import type { CaseSummary, DemoCase, HealthInfo } from "@/lib/review";
import { Button, Callout, Disclaimer, Field, Panel, Pill, inputClass } from "@/components/ui";

export default function Home() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [demos, setDemos] = useState<DemoCase[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [narrative, setNarrative] = useState("");
  const [drug, setDrug] = useState("");
  const [event, setEvent] = useState("");
  const [indication, setIndication] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [concomitant, setConcomitant] = useState("");
  const [comorbidities, setComorbidities] = useState("");
  const [demoId, setDemoId] = useState<string | null>(null);
  const [showContext, setShowContext] = useState(false);

  const refresh = useCallback(() => {
    api.listCases().then(setCases).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.getHealth().then(setHealth).catch((e) => setError(e.message));
    api.getDemoCases().then(setDemos).catch(() => undefined);
    refresh();
  }, [refresh]);

  const loadDemo = (demo: DemoCase) => {
    setNarrative(demo.narrative);
    setDrug(demo.suspected_drug);
    setEvent(demo.adverse_event);
    setIndication(demo.indication ?? "");
    setAge(demo.age ?? "");
    setSex(demo.sex ?? "");
    setConcomitant(demo.concomitant_medications ?? "");
    setComorbidities(demo.comorbidities ?? "");
    setDemoId(demo.case_id);
    if (demo.indication || demo.age) setShowContext(true);
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const env = await api.createCase({
        narrative: narrative.trim(),
        suspected_drug: drug.trim(),
        adverse_event: event.trim(),
        indication: indication || null,
        age: age || null,
        sex: sex || null,
        concomitant_medications: concomitant || null,
        comorbidities: comorbidities || null,
        demo_case_id: demoId,
      });
      router.push(`/case/${env.case.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const ready = narrative.trim() && drug.trim() && event.trim() && !busy;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-9">
      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-soft">CausalTrace</h1>
          {health && (
            <Pill tone={health.mode === "live" ? "accent" : "unknown"}>
              {health.mode} · {health.model}
            </Pill>
          )}
        </div>
        <p className="mt-2.5 max-w-3xl text-[13.5px] leading-relaxed text-slate-muted">
          An AI-assisted pharmacovigilance workspace. The AI extracts evidence, organises the case
          and suggests interpretations. You investigate, correct it, and decide.
        </p>
      </header>

      {error && (
        <div className="mb-6">
          <Callout tone="against" title="Problem">
            {error}
          </Callout>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel
          title="New case"
          subtitle="Paste an adverse-event case narrative, or load a demo case below."
        >
          {demos.length > 0 && (
            <div className="mb-5">
              <p className="mb-2 text-[11px] uppercase tracking-wider text-slate-muted">
                Demo cases
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {demos.map((demo) => (
                  <button
                    key={demo.case_id}
                    type="button"
                    onClick={() => loadDemo(demo)}
                    className={`rounded-lg border px-3 py-2.5 text-left transition ${
                      demoId === demo.case_id
                        ? "border-accent-500/70 bg-accent-500/10"
                        : "border-ink-700 bg-ink-850/60 hover:border-ink-600"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[12.5px] font-medium leading-snug text-slate-soft">
                        {demo.title}
                      </p>
                      {demo.is_ambiguous && (
                        <span className="mt-0.5 shrink-0 rounded-full border border-unknown-400/40 bg-unknown-bg px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-unknown-400">
                          ambiguous
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-muted">
                      {demo.description}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}

          <Field label="Case narrative">
            <textarea
              value={narrative}
              onChange={(e) => {
                setNarrative(e.target.value);
                setDemoId(null);
              }}
              rows={10}
              placeholder="A 34-year-old woman began TMP-SMX on March 2 for…"
              className={`${inputClass} resize-y font-mono leading-relaxed`}
            />
          </Field>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Suspected drug">
              <input value={drug} onChange={(e) => setDrug(e.target.value)} className={inputClass} />
            </Field>
            <Field label="Adverse event">
              <input value={event} onChange={(e) => setEvent(e.target.value)} className={inputClass} />
            </Field>
          </div>

          <button
            type="button"
            onClick={() => setShowContext((v) => !v)}
            className="mt-4 text-[11.5px] text-slate-muted underline decoration-dotted underline-offset-2 hover:text-accent-400"
          >
            {showContext ? "Hide" : "Add"} optional patient context
          </button>

          {showContext && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="Indication">
                <input value={indication} onChange={(e) => setIndication(e.target.value)} className={inputClass} />
              </Field>
              <Field label="Age">
                <input value={age} onChange={(e) => setAge(e.target.value)} className={inputClass} />
              </Field>
              <Field label="Sex">
                <input value={sex} onChange={(e) => setSex(e.target.value)} className={inputClass} />
              </Field>
              <Field label="Comorbidities">
                <input value={comorbidities} onChange={(e) => setComorbidities(e.target.value)} className={inputClass} />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Concomitant medications">
                  <input value={concomitant} onChange={(e) => setConcomitant(e.target.value)} className={inputClass} />
                </Field>
              </div>
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button tone="primary" disabled={!ready} busy={busy} onClick={start}>
              Start case review
            </Button>
            <p className="text-[11px] text-slate-muted">
              Opens a review workspace. No causality assessment is produced until you make one.
            </p>
          </div>
        </Panel>

        <div className="space-y-6">
          <Panel title="Open cases" subtitle={`${cases.length} case(s) in the workspace`}>
            {cases.length === 0 ? (
              <p className="text-[12.5px] text-slate-muted">
                No cases yet. Start one on the left — your review is saved as you go.
              </p>
            ) : (
              <ul className="space-y-2">
                {cases.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => router.push(`/case/${c.id}`)}
                      className="w-full rounded-lg border border-ink-700 bg-ink-850/50 px-3 py-2.5 text-left transition hover:border-accent-600/50"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="truncate text-[12.5px] font-medium text-slate-soft">
                          {c.title}
                        </p>
                        {c.signed_off ? (
                          <Pill tone="support">signed off</Pill>
                        ) : (
                          <Pill tone="neutral">{c.stage.toLowerCase()}</Pill>
                        )}
                      </div>
                      <p className="mt-1 text-[11px] text-slate-muted">
                        {c.final_assessment ? `Reviewer: ${c.final_assessment} · ` : ""}
                        updated {new Date(c.updated_at).toLocaleString()}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="How this works">
            <ol className="space-y-2 text-[12.5px] leading-relaxed text-slate-muted">
              {[
                "AI extracts candidate facts from the narrative.",
                "You accept, edit or reject each one.",
                "A timeline and competing causes are assembled from what you confirmed.",
                "The AI flags what information is missing.",
                "Formal frameworks populate from your answers, not the AI's.",
                "You write the conclusion; the report shows the full audit trail.",
              ].map((text, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="font-mono text-[11px] text-accent-400">{i + 1}</span>
                  {text}
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>

      <footer className="mt-8 border-t border-ink-700/60 pt-4">
        <Disclaimer />
      </footer>
    </main>
  );
}
