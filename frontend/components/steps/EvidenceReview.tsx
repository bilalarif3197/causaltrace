"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import {
  SECTION_LABELS,
  isPending,
  type Fact,
  type FactSection,
} from "@/lib/review";
import { Button, Callout, EmptyState, Field, Panel, Pill, WarnIcon, inputClass } from "../ui";
import { ReviewableCard } from "../review";
import type { StepProps } from "./types";

const SECTION_ORDER: FactSection[] = [
  "DRUG_EXPOSURE",
  "ADVERSE_EVENT",
  "OTHER_EXPOSURES",
  "MEDICAL_CONTEXT",
];

const FIELD_OPTIONS: Record<FactSection, { key: string; label: string }[]> = {
  DRUG_EXPOSURE: [
    { key: "suspected_drug", label: "Suspected drug" },
    { key: "dose", label: "Dose" },
    { key: "route", label: "Route" },
    { key: "start_date", label: "Start date" },
    { key: "stop_date", label: "Stop date" },
    { key: "duration", label: "Duration" },
    { key: "dose_changes", label: "Dose changes" },
  ],
  ADVERSE_EVENT: [
    { key: "event", label: "Adverse event" },
    { key: "onset_date", label: "Onset date" },
    { key: "severity", label: "Severity" },
    { key: "symptoms", label: "Relevant symptoms" },
    { key: "objective_tests", label: "Objective tests" },
    { key: "lab_abnormalities", label: "Lab abnormalities" },
  ],
  OTHER_EXPOSURES: [
    { key: "concomitant_medications", label: "Concomitant medication" },
    { key: "recently_stopped_medications", label: "Recently stopped medication" },
    { key: "alcohol", label: "Alcohol" },
    { key: "supplements", label: "Supplements" },
    { key: "recreational_drugs", label: "Recreational drugs" },
    { key: "infections", label: "Infection" },
  ],
  MEDICAL_CONTEXT: [
    { key: "comorbidities", label: "Comorbidity" },
    { key: "previous_similar_events", label: "Previous similar event" },
    { key: "baseline_labs", label: "Baseline labs" },
    { key: "relevant_diagnoses", label: "Relevant diagnosis" },
  ],
};

function AddFactForm({ caseId, section, onDone, run }: {
  caseId: string;
  section: FactSection;
  onDone: () => void;
  run: StepProps["run"];
}) {
  const [field, setField] = useState(FIELD_OPTIONS[section][0].key);
  const [value, setValue] = useState("");

  return (
    <div className="mt-2 rounded-lg border border-accent-600/40 bg-accent-500/5 p-3">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <Field label="Field">
          <select value={field} onChange={(e) => setField(e.target.value)} className={inputClass}>
            {FIELD_OPTIONS[section].map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Value">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="What the narrative says"
            className={inputClass}
          />
        </Field>
      </div>
      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          tone="primary"
          disabled={!value.trim()}
          onClick={async () => {
            await run(`add-${section}`, () =>
              api.addFact(caseId, { field, value: value.trim() }),
            );
            setValue("");
            onDone();
          }}
        >
          Add fact
        </Button>
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export default function EvidenceReview({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc, stats } = envelope;
  const [adding, setAdding] = useState<FactSection | null>(null);
  const extracting = busyKey === "suggest-facts";

  const bySection = (section: FactSection) => doc.facts.filter((f) => f.section === section);

  const reviewFact = (fact: Fact) => (action: Parameters<typeof api.reviewEntity>[3]) =>
    run(`fact-${fact.id}`, () => api.reviewEntity(doc.id, "fact", fact.id, action));

  return (
    <div className="space-y-5">
      <Panel
        title="AI case extraction"
        subtitle="Candidate facts pulled from the narrative. Nothing here counts as evidence until you accept it."
        aside={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              tone={doc.facts.length ? "ghost" : "primary"}
              busy={busyKey === "suggest-facts"}
              onClick={() => suggest("facts")}
            >
              {doc.facts.length ? "Re-run extraction" : "Extract evidence"}
            </Button>
            {stats.facts_pending > 0 && (
              <Button
                size="sm"
                busy={busyKey === "bulk-facts"}
                onClick={() =>
                  run("bulk-facts", () =>
                    api.bulkReview(doc.id, { entity_type: "fact", status: "REVIEWER_ACCEPTED" }),
                  )
                }
                title="Accept every item still awaiting review"
              >
                Accept all pending
              </Button>
            )}
          </div>
        }
      >
        {doc.facts.length === 0 ? (
          <EmptyState>
            {extracting
              ? "Reading the narrative and pulling out candidate facts…"
              : "No facts extracted yet. Run the extraction to get candidate facts, then accept, edit or reject each one. You can also add facts the AI missed."}
          </EmptyState>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Pill tone="support">{stats.facts_accepted} accepted</Pill>
            <Pill tone="accent">{stats.facts_modified} modified</Pill>
            <Pill tone="against">{stats.facts_rejected} rejected</Pill>
            <Pill tone={stats.facts_pending ? "unknown" : "neutral"}>
              {stats.facts_pending} awaiting review
            </Pill>
            {stats.facts_unsupported > 0 && (
              <Pill tone="against" title="Verification could not confirm the cited evidence">
                <WarnIcon className="h-3 w-3" />
                {stats.facts_unsupported} failed verification
              </Pill>
            )}
          </div>
        )}
      </Panel>

      {stats.facts_unsupported > 0 && (
        <Callout tone="against" title="Some citations did not hold up">
          The verifier re-read the narrative and could not confirm {stats.facts_unsupported}{" "}
          claim(s) against the text cited for them. They are marked{" "}
          <strong className="text-unknown-400">Needs review</strong> rather than deleted, so you
          can judge them yourself.
        </Callout>
      )}

      {SECTION_ORDER.map((section) => {
        const facts = bySection(section);
        const pending = facts.filter((f) => isPending(f.reviewer_status)).length;
        return (
          <Panel
            key={section}
            title={SECTION_LABELS[section]}
            subtitle={`${facts.length} item(s)${pending ? ` · ${pending} awaiting review` : ""}`}
            aside={
              <Button size="sm" onClick={() => setAdding(adding === section ? null : section)}>
                + Add fact
              </Button>
            }
          >
            {adding === section && (
              <AddFactForm
                caseId={doc.id}
                section={section}
                run={run}
                onDone={() => setAdding(null)}
              />
            )}

            {facts.length === 0 ? (
              <p className="mt-2 text-[12.5px] italic text-slate-muted">
                {extracting
                  ? "Extracting…"
                  : "Nothing extracted for this section. If the narrative covers it, add it manually."}
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {facts.map((fact) => (
                  <ReviewableCard
                    key={fact.id}
                    item={fact}
                    title={fact.label}
                    activeSpanId={active?.sourceId}
                    onSelectSpan={onSelectSpan}
                    onReview={reviewFact(fact)}
                    busy={busyKey === `fact-${fact.id}`}
                  />
                ))}
              </ul>
            )}
          </Panel>
        );
      })}
    </div>
  );
}
