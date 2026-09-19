"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import {
  DIMENSION_LABELS,
  SECTION_LABELS,
  confirmedValue,
  type AuditEntry,
  type DimensionName,
  type FactSection,
} from "@/lib/review";
import { Button, Callout, Panel, Pill } from "../ui";
import type { StepProps } from "./types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-ink-700/60 px-5 py-4 first:border-t-0">
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-400">
        {title}
      </h3>
      {children}
    </section>
  );
}

export default function Report({ envelope }: StepProps) {
  const { case: doc, stats, framework } = envelope;
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    api.getAudit(doc.id).then(setAudit).catch(() => undefined);
  }, [doc.id, doc.updated_at]);

  const confirmed = doc.facts.filter((f) =>
    ["REVIEWER_ACCEPTED", "REVIEWER_MODIFIED"].includes(f.reviewer_status),
  );
  const timeline = [...doc.timeline].sort((a, b) => a.order_index - b.order_index);
  const assessed = doc.hypotheses.filter((h) => h.reviewer_assessment);
  const primary = doc.hypotheses.find((h) => h.id === doc.conclusion.primary_cause_hypothesis_id);
  const gaps = doc.missing_evidence.filter((m) => m.status !== "NOT_RELEVANT");

  const aiSuggested = stats.ai_suggestions_total;
  const correctionRate = aiSuggested ? Math.round((stats.reviewer_corrections / aiSuggested) * 100) : 0;

  return (
    <div className="space-y-5">
      <Panel
        title="Case report"
        subtitle="Everything below reflects reviewer-confirmed evidence and the reviewer's own conclusion."
        aside={
          <div className="flex gap-2">
            {doc.conclusion.signed_off ? (
              <Pill tone="support">✓ signed off</Pill>
            ) : (
              <Pill tone="unknown">draft — not signed off</Pill>
            )}
            <Button size="sm" onClick={() => window.print()}>
              Print / PDF
            </Button>
          </div>
        }
        bodyClassName="p-0"
      >
        <Section title="Case">
          <dl className="grid gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-2">
            {[
              ["Suspected drug", doc.suspected_drug],
              ["Adverse event", doc.adverse_event],
              ["Indication", doc.patient.indication],
              ["Age / sex", [doc.patient.age, doc.patient.sex].filter(Boolean).join(" / ")],
              ["Comorbidities", doc.patient.comorbidities],
              ["Concomitant medications", doc.patient.concomitant_medications],
            ]
              .filter(([, v]) => v)
              .map(([label, value]) => (
                <div key={label as string} className="flex gap-2">
                  <dt className="shrink-0 text-slate-muted">{label}:</dt>
                  <dd className="text-slate-soft">{value}</dd>
                </div>
              ))}
          </dl>
        </Section>

        <Section title="Reviewer conclusion">
          {doc.conclusion.final_assessment ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="accent" className="!text-[12px]">
                  {doc.conclusion.final_assessment}
                </Pill>
                {primary && <span className="text-[12.5px] text-slate-soft">— {primary.label}</span>}
              </div>
              {doc.conclusion.reviewer_rationale && (
                <p className="mt-3 whitespace-pre-wrap text-[12.5px] leading-relaxed text-slate-soft">
                  {doc.conclusion.reviewer_rationale}
                </p>
              )}
            </>
          ) : (
            <p className="text-[12.5px] italic text-slate-muted">
              No conclusion recorded yet. Complete the Conclusion step.
            </p>
          )}
        </Section>

        <Section title="Clinical timeline">
          {timeline.length === 0 ? (
            <p className="text-[12.5px] italic text-slate-muted">No timeline recorded.</p>
          ) : (
            <ol className="space-y-1">
              {timeline.map((e) => (
                <li key={e.id} className="flex gap-3 text-[12.5px]">
                  <span className="w-24 shrink-0 font-mono text-[11px] text-accent-400">
                    {e.display_date || e.relative_text || `Step ${e.order_index}`}
                  </span>
                  <span className="text-slate-soft">
                    {e.label}
                    {e.timing_uncertain && (
                      <span className="ml-1.5 text-[10.5px] text-unknown-400">(timing uncertain)</span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>

        <Section title={`Key evidence (${confirmed.length} reviewer-confirmed)`}>
          {confirmed.length === 0 ? (
            <p className="text-[12.5px] italic text-slate-muted">
              No evidence has been confirmed, so no assessment can rest on it.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {(Object.keys(SECTION_LABELS) as FactSection[]).map((section) => {
                const facts = confirmed.filter((f) => f.section === section);
                if (!facts.length) return null;
                return (
                  <div key={section}>
                    <p className="mb-1 text-[10.5px] uppercase tracking-wider text-slate-muted">
                      {SECTION_LABELS[section]}
                    </p>
                    <ul className="space-y-0.5">
                      {facts.map((f) => (
                        <li key={f.id} className="text-[12px] text-slate-soft">
                          <span className="text-slate-muted">{f.label}:</span>{" "}
                          {confirmedValue(f)}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </Section>

        {doc.dimensions.length > 0 && (
          <Section title="Causality dimensions">
            <ul className="space-y-1">
              {doc.dimensions
                .filter((d) => confirmedValue(d))
                .map((d) => (
                  <li key={d.id} className="text-[12px]">
                    <span className="text-slate-muted">
                      [{DIMENSION_LABELS[d.dimension as DimensionName]}] {d.question}
                    </span>{" "}
                    <span className="text-slate-soft">→ {confirmedValue(d)}</span>
                  </li>
                ))}
            </ul>
          </Section>
        )}

        <Section title="Alternative etiologies considered">
          {assessed.length === 0 ? (
            <p className="text-[12.5px] italic text-slate-muted">None assessed.</p>
          ) : (
            <ul className="space-y-1.5">
              {assessed.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                  <span className="text-slate-soft">{h.label}</span>
                  <Pill
                    tone={
                      h.reviewer_assessment === "Strongly supported"
                        ? "support"
                        : h.reviewer_assessment === "Not supported"
                          ? "against"
                          : "neutral"
                    }
                  >
                    {h.reviewer_assessment}
                  </Pill>
                  {h.ai_assessment && h.ai_assessment !== h.reviewer_assessment && (
                    <span className="text-[10.5px] text-violet-300">
                      (AI said {h.ai_assessment})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Missing evidence">
          {gaps.length === 0 ? (
            <p className="text-[12.5px] italic text-slate-muted">None recorded.</p>
          ) : (
            <ul className="space-y-1">
              {gaps.map((m) => (
                <li key={m.id} className="text-[12px] text-slate-soft">
                  <span className="text-slate-muted">[{m.status.replace(/_/g, " ").toLowerCase()}]</span>{" "}
                  {m.prompt}
                </li>
              ))}
            </ul>
          )}
        </Section>

        {framework && (
          <Section title="Naranjo framework result">
            <p className="text-[12.5px] text-slate-soft">
              Score{" "}
              <span className="font-mono text-accent-400">
                {framework.total_score > 0 ? `+${framework.total_score}` : framework.total_score}
              </span>{" "}
              → {framework.classification}
              {framework.unknown_count > 0 && (
                <span className="text-slate-muted">
                  {" "}
                  · {framework.unknown_count}/10 UNKNOWN · possible range{" "}
                  {framework.score_floor} to {framework.score_ceiling}
                  {!framework.classification_is_stable && " (classification not stable)"}
                </span>
              )}
            </p>
            {framework.unreviewed_count > 0 && (
              <p className="mt-1 text-[11.5px] text-unknown-400">
                {framework.unreviewed_count} item(s) were never reviewed and scored zero.
              </p>
            )}
          </Section>
        )}

        {doc.who_umc?.reviewer_classification && (
          <Section title="WHO-UMC assessment">
            <p className="text-[12.5px] text-slate-soft">
              {doc.who_umc.reviewer_classification}
              {doc.who_umc.ai_classification !== doc.who_umc.reviewer_classification && (
                <span className="ml-2 text-[10.5px] text-violet-300">
                  (AI suggested {doc.who_umc.ai_classification})
                </span>
              )}
            </p>
          </Section>
        )}
      </Panel>

      <Panel
        title="AI assistance audit"
        subtitle="What the machine proposed, and what the human did about it."
        aside={
          <Button size="sm" onClick={() => setShowLog((v) => !v)}>
            {showLog ? "Hide" : "Show"} full log ({audit.length})
          </Button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["AI suggestions", aiSuggested, "neutral"],
            ["Reviewer accepted", stats.facts_accepted, "support"],
            ["Reviewer modified", stats.facts_modified, "accent"],
            ["Reviewer rejected", stats.facts_rejected, "against"],
          ].map(([label, value, tone]) => (
            <div key={label as string} className="rounded-lg border border-ink-700 bg-ink-850/50 px-3.5 py-3">
              <p className="font-mono text-xl font-semibold leading-none text-slate-soft">
                {value as number}
              </p>
              <p className="mt-1 text-[10.5px] uppercase tracking-wider text-slate-muted">{label}</p>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <Callout tone={correctionRate > 0 ? "accent" : "neutral"} title="Reviewer correction rate">
            The reviewer changed or discarded{" "}
            <strong className="font-mono">{correctionRate}%</strong> of the {aiSuggested} items the
            AI proposed ({stats.reviewer_corrections} correction
            {stats.reviewer_corrections === 1 ? "" : "s"}). A rate of zero on a real case usually
            means the review was not adversarial enough, not that the AI was perfect.
          </Callout>
        </div>

        <div className="mt-4 space-y-1.5 text-[12.5px] text-slate-soft">
          <p>
            AI suggested {doc.hypotheses.filter((h) => h.origin === "AI").length} alternative
            cause(s); reviewer retained {stats.hypotheses_retained} as plausible.
          </p>
          {framework && (
            <p>
              Naranjo framework result:{" "}
              <strong>{framework.classification}</strong>. Final reviewer conclusion:{" "}
              <strong>{doc.conclusion.final_assessment ?? "not recorded"}</strong>.
            </p>
          )}
          {doc.model_used && (
            <p className="text-slate-muted">
              Model: {doc.model_used} ({doc.mode} mode)
            </p>
          )}
        </div>

        {showLog && (
          <ul className="mt-4 max-h-96 space-y-1 overflow-y-auto border-t border-ink-700/60 pt-3">
            {audit.map((e) => (
              <li key={e.id} className="flex gap-2.5 text-[11.5px]">
                <span
                  className={`w-16 shrink-0 font-mono ${
                    e.actor === "AI" ? "text-violet-300" : "text-accent-400"
                  }`}
                >
                  {e.actor}
                </span>
                <span className="w-36 shrink-0 font-mono text-slate-muted">{e.action}</span>
                <span className="flex-1 text-slate-soft">{e.summary}</span>
                <span className="shrink-0 text-slate-muted">
                  {new Date(e.at).toLocaleTimeString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
