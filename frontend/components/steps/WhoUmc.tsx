"use client";

import * as api from "@/lib/api";
import { AiIcon, Button, Callout, EmptyState, Field, Panel, Pill, inputClass } from "../ui";
import { SourceQuote, StatusChip } from "../review";
import type { StepProps } from "./types";

const CATEGORIES = [
  "Certain",
  "Probable",
  "Possible",
  "Unlikely",
  "Conditional/Unclassified",
  "Unassessable/Unclassifiable",
];

export default function WhoUmc({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc } = envelope;
  const umc = doc.who_umc;

  return (
    <div className="space-y-5">
      <Panel
        title="WHO-UMC assessment"
        subtitle="A category judgment, not an arithmetic score. The AI can summarise why the evidence fits a category; you choose the category."
        aside={
          <Button
            size="sm"
            tone={umc ? "ghost" : "primary"}
            busy={busyKey === "suggest-who_umc"}
            onClick={() => suggest("who_umc")}
          >
            {umc ? "Re-run" : "Suggest category"}
          </Button>
        }
        className="border-indigo-400/25"
      >
        {!umc ? (
          <EmptyState>
            Not assessed yet. Unlike Naranjo, WHO-UMC has no formula — it weighs clinical
            plausibility, so there is nothing to compute and everything to judge.
          </EmptyState>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <StatusChip status={umc.reviewer_status} />
              {umc.ai_classification && (
                <Pill tone="ai">
                  <AiIcon className="h-3 w-3" />
                  AI suggests: {umc.ai_classification}
                </Pill>
              )}
              {umc.reviewer_classification && (
                <Pill
                  tone={umc.reviewer_classification === umc.ai_classification ? "support" : "accent"}
                >
                  Reviewer: {umc.reviewer_classification}
                </Pill>
              )}
            </div>

            {umc.ai_reasoning && (
              <p className="text-[12.5px] leading-relaxed text-slate-soft">{umc.ai_reasoning}</p>
            )}

            {umc.key_evidence.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
                  Evidence driving this
                </h3>
                <ul className="space-y-1.5">
                  {umc.key_evidence.map((item) => {
                    const isActive = active?.sourceId === item.id;
                    return (
                      <li
                        key={item.id}
                        className="rounded-lg border border-ink-700/60 bg-ink-850/40 px-3 py-2"
                      >
                        <p className="text-[12px] leading-snug text-slate-soft">{item.statement}</p>
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
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {umc.ai_major_uncertainty && (
              <div className="mt-4">
                <Callout tone="unknown" title="Major uncertainty">
                  {umc.ai_major_uncertainty}
                </Callout>
              </div>
            )}

            <div className="mt-4 border-t border-ink-700/60 pt-3.5">
              <Field
                label="Your WHO-UMC category"
                hint="Your selection is authoritative and is what appears in the report."
              >
                <select
                  value={umc.reviewer_classification ?? ""}
                  disabled={busyKey === "umc"}
                  onChange={(e) =>
                    run("umc", () =>
                      api.reviewEntity(doc.id, "who_umc", "current", { value: e.target.value }),
                    )
                  }
                  className={inputClass}
                >
                  <option value="" disabled>
                    Select a category…
                  </option>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
