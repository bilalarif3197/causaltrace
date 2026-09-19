"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import {
  ASSESSMENT_LEVELS,
  type AssessmentLevel,
  type EvidenceValence,
  type Hypothesis,
  type HypothesisEvidence,
} from "@/lib/review";
import { AiIcon, Button, CheckIcon, EmptyState, Field, Panel, Pill, QuestionIcon, WarnIcon, inputClass } from "../ui";
import { SourceQuote, StatusChip } from "../review";
import CausalGraph from "../CausalGraph";
import type { StepProps } from "./types";

const VALENCE_META: Record<
  EvidenceValence,
  { label: string; icon: (p: { className?: string }) => React.ReactElement; tone: string }
> = {
  SUPPORTING: { label: "Supports", icon: CheckIcon, tone: "text-support-400" },
  CONTRADICTING: { label: "Argues against", icon: WarnIcon, tone: "text-against-400" },
  UNKNOWN: { label: "Not reported", icon: QuestionIcon, tone: "text-unknown-400" },
};

function EvidenceList({
  items,
  valence,
  caseId,
  run,
  busyKey,
  active,
  onSelectSpan,
}: {
  items: HypothesisEvidence[];
  valence: EvidenceValence;
  caseId: string;
  run: StepProps["run"];
  busyKey: string | null;
  active: StepProps["active"];
  onSelectSpan: StepProps["onSelectSpan"];
}) {
  const meta = VALENCE_META[valence];
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <meta.icon className={`h-3.5 w-3.5 ${meta.tone}`} />
        <h4 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
          {meta.label}
        </h4>
        <span className="font-mono text-[10.5px] text-slate-muted">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-ink-700 px-2.5 py-2 text-[11.5px] italic text-slate-muted">
          {valence === "CONTRADICTING"
            ? "Nothing argues against this — which is not the same as evidence for it."
            : "None recorded."}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => {
            const isActive = active?.sourceId === item.id;
            const rejected = item.reviewer_status === "REVIEWER_REJECTED";
            return (
              <li
                key={item.id}
                className={`rounded-lg border px-2.5 py-2 ${
                  rejected
                    ? "border-ink-700/60 bg-ink-900/40 opacity-55"
                    : isActive
                      ? "border-accent-500/60 bg-accent-500/5"
                      : "border-ink-700/60 bg-ink-850/40"
                }`}
              >
                <p
                  className={`text-[12px] leading-snug ${
                    rejected ? "text-slate-muted line-through" : "text-slate-soft"
                  }`}
                >
                  {item.statement}
                </p>
                <SourceQuote
                  item={item}
                  isActive={isActive}
                  onSelect={() => {
                    const span = item.ai?.span;
                    if (!span || span.start == null) return;
                    onSelectSpan(
                      isActive ? null : { span, sourceId: item.id, label: item.statement },
                    );
                  }}
                />
                <div className="mt-1.5 flex items-center gap-1.5">
                  <StatusChip status={item.reviewer_status} />
                  <button
                    type="button"
                    onClick={() =>
                      run(`hev-${item.id}`, () =>
                        api.reviewEntity(caseId, "hypothesis_evidence", item.id, {
                          status: rejected ? "AI_SUGGESTED" : "REVIEWER_REJECTED",
                        }),
                      )
                    }
                    disabled={busyKey === `hev-${item.id}`}
                    className="text-[10.5px] text-slate-muted underline decoration-dotted underline-offset-2 hover:text-against-400 disabled:opacity-40"
                  >
                    {rejected ? "restore" : "exclude"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function HypothesisPanel({
  hypothesis,
  caseId,
  run,
  busyKey,
  active,
  onSelectSpan,
}: {
  hypothesis: Hypothesis;
  caseId: string;
  run: StepProps["run"];
  busyKey: string | null;
  active: StepProps["active"];
  onSelectSpan: StepProps["onSelectSpan"];
}) {
  const key = `hyp-${hypothesis.id}`;
  const bucket = (v: EvidenceValence) => hypothesis.evidence.filter((e) => e.valence === v);

  return (
    <Panel
      title={hypothesis.is_suspected_drug ? "Suspected drug" : hypothesis.kind.replace(/_/g, " ").toLowerCase()}
      subtitle={hypothesis.label}
      className={hypothesis.is_suspected_drug ? "border-accent-600/35" : ""}
      aside={
        <div className="flex flex-col items-end gap-1.5">
          <StatusChip status={hypothesis.reviewer_status} />
          {hypothesis.ai_assessment && (
            <span className="text-[10.5px] text-violet-300">
              <AiIcon className="h-2.5 w-2.5" />
              AI: {hypothesis.ai_assessment}
            </span>
          )}
        </div>
      }
    >
      {hypothesis.ai_rationale && (
        <p className="mb-3.5 rounded-lg border-l-2 border-violet-400/50 bg-ink-850/60 px-3 py-2 text-[12px] leading-relaxed text-slate-soft">
          {hypothesis.ai_rationale}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {(["SUPPORTING", "CONTRADICTING", "UNKNOWN"] as EvidenceValence[]).map((v) => (
          <EvidenceList
            key={v}
            valence={v}
            items={bucket(v)}
            caseId={caseId}
            run={run}
            busyKey={busyKey}
            active={active}
            onSelectSpan={onSelectSpan}
          />
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-ink-700/60 pt-3.5">
        <div className="min-w-[14rem] flex-1">
          <Field
            label="Your assessment"
            hint="Your choice is authoritative. The AI's suggestion is recorded beside it, not merged into it."
          >
            <select
              value={hypothesis.reviewer_assessment ?? ""}
              disabled={busyKey === key}
              onChange={(e) =>
                run(key, () =>
                  api.reviewEntity(caseId, "hypothesis", hypothesis.id, { value: e.target.value }),
                )
              }
              className={inputClass}
            >
              <option value="" disabled>
                Select an assessment…
              </option>
              {ASSESSMENT_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {hypothesis.reviewer_assessment && (
          <Pill
            tone={
              hypothesis.reviewer_assessment === hypothesis.ai_assessment ? "support" : "accent"
            }
            className="mb-1"
          >
            {hypothesis.reviewer_assessment === hypothesis.ai_assessment
              ? "agrees with AI"
              : "overrides AI"}
          </Pill>
        )}
      </div>
    </Panel>
  );
}

export default function Hypotheses({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc, stats } = envelope;
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [focused, setFocused] = useState<string | null>(null);

  // Keep focus on a hypothesis that still exists after a re-run.
  useEffect(() => {
    if (focused && !doc.hypotheses.some((h) => h.id === focused)) setFocused(null);
  }, [doc.hypotheses, focused]);

  const ordered = focused
    ? [...doc.hypotheses].sort((a, b) => (a.id === focused ? -1 : b.id === focused ? 1 : 0))
    : doc.hypotheses;

  return (
    <div className="space-y-5">
      <Panel
        title="Competing causal hypotheses"
        subtitle="Every explanation the case supports, weighed separately. A temporal relationship is not causality — the point of this step is to keep the alternatives visible."
        aside={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              tone={doc.hypotheses.length ? "ghost" : "primary"}
              busy={busyKey === "suggest-hypotheses"}
              onClick={() => suggest("hypotheses")}
            >
              {doc.hypotheses.length ? "Re-run suggestions" : "Suggest causes"}
            </Button>
            <Button size="sm" onClick={() => setAdding((v) => !v)}>
              + Add cause
            </Button>
          </div>
        }
      >
        {doc.hypotheses.length === 0 ? (
          <EmptyState>
            No hypotheses yet. The AI will propose the suspected drug plus every alternative the
            narrative supports — concomitant drugs, infection, underlying disease, alcohol,
            procedures. You decide how strongly each is supported.
          </EmptyState>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Pill tone="support">{stats.hypotheses_assessed} assessed</Pill>
            <Pill tone={stats.hypotheses_total - stats.hypotheses_assessed ? "unknown" : "neutral"}>
              {stats.hypotheses_total - stats.hypotheses_assessed} unassessed
            </Pill>
            <Pill tone="accent">{stats.hypotheses_retained} retained as plausible</Pill>
          </div>
        )}

        {adding && (
          <div className="mt-4 rounded-lg border border-accent-600/40 bg-accent-500/5 p-3">
            <Field label="Alternative cause">
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Recent contrast exposure"
                className={inputClass}
              />
            </Field>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                tone="primary"
                disabled={!label.trim()}
                busy={busyKey === "add-hyp"}
                onClick={async () => {
                  await run("add-hyp", () => api.addHypothesis(doc.id, { label: label.trim() }));
                  setLabel("");
                  setAdding(false);
                }}
              >
                Add hypothesis
              </Button>
              <Button size="sm" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </Panel>

      {doc.hypotheses.length > 0 && (
        <Panel
          title="Causal map"
          subtitle="Edges show YOUR assessment. An unassessed hypothesis stays faint rather than borrowing the AI's opinion."
          bodyClassName="p-0"
        >
          <CausalGraph
            hypotheses={doc.hypotheses}
            adverseEvent={doc.adverse_event}
            selectedId={focused}
            onSelect={(id) => setFocused(id === focused ? null : id)}
          />
        </Panel>
      )}

      {ordered.map((h) => (
        <HypothesisPanel
          key={h.id}
          hypothesis={h}
          caseId={doc.id}
          run={run}
          busyKey={busyKey}
          active={active}
          onSelectSpan={onSelectSpan}
        />
      ))}
    </div>
  );
}
