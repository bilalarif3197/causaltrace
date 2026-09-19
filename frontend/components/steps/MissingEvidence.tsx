"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import { MISSING_STATUSES, type MissingStatus } from "@/lib/review";
import { Button, EmptyState, Field, Panel, Pill, inputClass } from "../ui";
import type { StepProps } from "./types";

const STATUS_TONE: Record<MissingStatus, "unknown" | "accent" | "against" | "neutral" | "support"> = {
  OPEN: "unknown",
  OBTAINABLE: "accent",
  UNAVAILABLE: "against",
  NOT_RELEVANT: "neutral",
  ADDED_TO_CASE: "support",
};

export default function MissingEvidence({ envelope, run, suggest, busyKey }: StepProps) {
  const { case: doc, stats } = envelope;
  const [adding, setAdding] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [why, setWhy] = useState("");

  return (
    <div className="space-y-5">
      <Panel
        title="What information would reduce uncertainty?"
        subtitle="Gaps in the case that materially limit the assessment. Suggested from the evidence you have already confirmed, so it reflects the case as you validated it — not the AI's first pass."
        aside={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              tone={doc.missing_evidence.length ? "ghost" : "primary"}
              busy={busyKey === "suggest-missing"}
              onClick={() => suggest("missing")}
            >
              {doc.missing_evidence.length ? "Re-run" : "Find gaps"}
            </Button>
            <Button size="sm" onClick={() => setAdding((v) => !v)}>
              + Add gap
            </Button>
          </div>
        }
      >
        {doc.missing_evidence.length === 0 ? (
          <EmptyState>
            Nothing identified yet. This step turns the assessment from a verdict into an
            investigation: what would you need to go and find in order to tell the competing
            explanations apart?
          </EmptyState>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Pill tone={stats.missing_open ? "unknown" : "support"}>
              {stats.missing_open} still open
            </Pill>
            <Pill tone="neutral">{stats.missing_total} identified</Pill>
          </div>
        )}

        {adding && (
          <div className="mt-4 rounded-lg border border-accent-600/40 bg-accent-500/5 p-3">
            <Field label="Missing information">
              <input
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g. Serum drug concentration at presentation"
                className={inputClass}
              />
            </Field>
            <div className="mt-3">
              <Field label="Why it matters">
                <input
                  value={why}
                  onChange={(e) => setWhy(e.target.value)}
                  placeholder="How would having it change the assessment?"
                  className={inputClass}
                />
              </Field>
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                tone="primary"
                disabled={!prompt.trim()}
                busy={busyKey === "add-missing"}
                onClick={async () => {
                  await run("add-missing", () =>
                    api.addMissing(doc.id, { prompt: prompt.trim(), why_it_matters: why.trim() }),
                  );
                  setPrompt("");
                  setWhy("");
                  setAdding(false);
                }}
              >
                Add
              </Button>
              <Button size="sm" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </Panel>

      {doc.missing_evidence.length > 0 && (
        <Panel title="Information gaps" bodyClassName="p-4">
          <ul className="space-y-2.5">
            {doc.missing_evidence.map((item) => {
              const key = `miss-${item.id}`;
              return (
                <li
                  key={item.id}
                  className={`rounded-lg border px-3.5 py-3 ${
                    item.status === "OPEN"
                      ? "border-unknown-400/30 bg-unknown-bg/30"
                      : "border-ink-700/60 bg-ink-850/40"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="flex-1 text-[13px] font-medium leading-snug text-slate-soft">
                      {item.prompt}
                    </p>
                    <Pill tone={STATUS_TONE[item.status]}>
                      {MISSING_STATUSES.find((s) => s.value === item.status)?.label}
                    </Pill>
                  </div>

                  {item.why_it_matters && (
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-muted">
                      {item.why_it_matters}
                    </p>
                  )}

                  {item.affects.length > 0 && (
                    <p className="mt-1.5 text-[10.5px] text-slate-muted">
                      Affects: {item.affects.join(" · ")}
                    </p>
                  )}

                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    {MISSING_STATUSES.filter((s) => s.value !== "OPEN").map((s) => (
                      <Button
                        key={s.value}
                        size="sm"
                        tone={item.status === s.value ? "primary" : "ghost"}
                        busy={busyKey === key}
                        onClick={() =>
                          run(key, () =>
                            api.reviewEntity(doc.id, "missing", item.id, {
                              value: item.status === s.value ? "OPEN" : s.value,
                            }),
                          )
                        }
                      >
                        {s.label}
                      </Button>
                    ))}
                    {item.origin === "REVIEWER" && <Pill tone="accent">reviewer-added</Pill>}
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}
    </div>
  );
}
