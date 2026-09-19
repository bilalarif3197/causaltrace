"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import { Button, Callout, Field, Panel, Pill, inputClass } from "../ui";
import type { StepProps } from "./types";

const ASSESSMENTS = [
  "Certain",
  "Probable / Likely",
  "Possible",
  "Unlikely",
  "Conditional / Unclassified",
  "Unassessable / Unclassifiable",
];

export default function Conclusion({ envelope, run, suggest, busyKey }: StepProps) {
  const { case: doc, framework } = envelope;
  const c = doc.conclusion;

  const [rationale, setRationale] = useState(c.reviewer_rationale || c.ai_draft_rationale || "");
  const [dirty, setDirty] = useState(false);

  // Pull in a freshly drafted rationale, but never clobber unsaved edits.
  useEffect(() => {
    if (!dirty) setRationale(c.reviewer_rationale || c.ai_draft_rationale || "");
  }, [c.reviewer_rationale, c.ai_draft_rationale, dirty]);

  const assessed = doc.hypotheses.filter((h) => h.reviewer_assessment);

  return (
    <div className="space-y-5">
      <Panel
        title="Reviewer conclusion"
        subtitle="Your judgment. The frameworks inform it; they do not make it."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Final reviewer assessment"
            hint="WHO-UMC compatible terminology."
          >
            <select
              value={c.final_assessment ?? ""}
              disabled={busyKey === "conclusion"}
              onChange={(e) =>
                run("conclusion", () =>
                  api.setConclusion(doc.id, { final_assessment: e.target.value }),
                )
              }
              className={inputClass}
            >
              <option value="" disabled>
                Select your assessment…
              </option>
              {ASSESSMENTS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Primary suspected cause"
            hint={assessed.length ? undefined : "Assess a hypothesis first to choose one."}
          >
            <select
              value={c.primary_cause_hypothesis_id ?? ""}
              disabled={busyKey === "conclusion" || assessed.length === 0}
              onChange={(e) =>
                run("conclusion", () =>
                  api.setConclusion(doc.id, {
                    primary_cause_hypothesis_id: e.target.value || null,
                  }),
                )
              }
              className={inputClass}
            >
              <option value="">No single cause identified</option>
              {assessed.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.label} — {h.reviewer_assessment}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {framework && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Pill tone="neutral">
              Naranjo framework: {framework.total_score > 0 ? `+${framework.total_score}` : framework.total_score} ·{" "}
              {framework.classification}
            </Pill>
            {doc.who_umc?.reviewer_classification && (
              <Pill tone="neutral">WHO-UMC: {doc.who_umc.reviewer_classification}</Pill>
            )}
            {c.final_assessment &&
              framework.classification.toLowerCase() !==
                c.final_assessment.split(" ")[0].toLowerCase() && (
                <Pill tone="accent" title="Your conclusion departs from the framework result">
                  you departed from the framework
                </Pill>
              )}
          </div>
        )}
      </Panel>

      <Panel
        title="Reviewer rationale"
        subtitle="Drafted from evidence you confirmed — rejected and unreviewed items are never shown to the drafter."
        aside={
          <Button
            size="sm"
            busy={busyKey === "suggest-rationale"}
            onClick={() => suggest("rationale")}
          >
            ✨ {c.ai_draft_rationale ? "Re-draft" : "Draft rationale"}
          </Button>
        }
      >
        {c.ai_draft_rationale && (
          <div className="mb-3">
            <Callout tone="ai" title="AI-generated draft — reviewer confirmation required">
              This text was written by a model from your confirmed evidence. Edit it freely; what
              you save is what appears in the report.
            </Callout>
          </div>
        )}

        <textarea
          value={rationale}
          onChange={(e) => {
            setRationale(e.target.value);
            setDirty(true);
          }}
          rows={9}
          placeholder="Explain the temporal relationship, dechallenge and rechallenge status, the competing explanations you considered, and what could not be determined."
          className={`${inputClass} resize-y leading-relaxed`}
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            tone="primary"
            size="sm"
            disabled={!rationale.trim()}
            busy={busyKey === "rationale-save"}
            onClick={async () => {
              await run("rationale-save", () =>
                api.setConclusion(doc.id, { reviewer_rationale: rationale }),
              );
              setDirty(false);
            }}
          >
            Save rationale
          </Button>
          {dirty && <span className="text-[11px] text-unknown-400">unsaved changes</span>}
          {!dirty && c.rationale_status === "REVIEWER_MODIFIED" && (
            <Pill tone="accent">edited by reviewer</Pill>
          )}
          {!dirty && c.rationale_status === "REVIEWER_ACCEPTED" && (
            <Pill tone="support">accepted AI draft unchanged</Pill>
          )}
        </div>
      </Panel>

      <Panel title="Sign off">
        <p className="text-[12.5px] leading-relaxed text-slate-soft">
          Signing off records that this conclusion is yours and freezes it into the case report.
          You can still reopen and change it — every change is recorded in the audit trail.
        </p>
        <div className="mt-3.5 flex flex-wrap items-center gap-3">
          <Button
            tone={c.signed_off ? "ghost" : "primary"}
            busy={busyKey === "signoff"}
            disabled={!c.final_assessment || !rationale.trim()}
            onClick={() =>
              run("signoff", () => api.setConclusion(doc.id, { signed_off: !c.signed_off }))
            }
          >
            {c.signed_off ? "Reopen case" : "Sign off conclusion"}
          </Button>
          {c.signed_off && <Pill tone="support">✓ signed off</Pill>}
          {!c.final_assessment && (
            <span className="text-[11px] text-slate-muted">
              Select a final assessment first.
            </span>
          )}
          {c.final_assessment && !rationale.trim() && (
            <span className="text-[11px] text-slate-muted">Write a rationale first.</span>
          )}
        </div>
      </Panel>
    </div>
  );
}
