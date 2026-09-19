"use client";

import * as api from "@/lib/api";
import {
  DIMENSION_LABELS,
  isPending,
  type DimensionName,
  type DimensionQuestion,
} from "@/lib/review";
import { Button, Callout, EmptyState, Panel, Pill } from "../ui";
import { ReviewableCard } from "../review";
import type { StepProps } from "./types";

const ORDER: DimensionName[] = [
  "TEMPORALITY",
  "DECHALLENGE",
  "RECHALLENGE",
  "DOSE_RELATIONSHIP",
];

const GUIDANCE: Record<DimensionName, string> = {
  TEMPORALITY:
    "Did exposure precede the event, and is the latency plausible? This is the single heaviest-weighted element of most causality frameworks.",
  DECHALLENGE:
    "What happened after the drug was stopped — and could anything else explain the improvement?",
  RECHALLENGE:
    "Was the drug restarted? If it never was, that is UNKNOWN, not a negative finding. Absence of a rechallenge is not evidence against causality.",
  DOSE_RELATIONSHIP:
    "Did severity track the dose? Usually unavailable, which is itself worth recording.",
  ALTERNATIVE_ETIOLOGIES:
    "Competing explanations are handled on the next step, where each becomes its own hypothesis.",
};

export default function Investigation({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc, stats } = envelope;

  const forDimension = (d: DimensionName) => doc.dimensions.filter((q) => q.dimension === d);

  const review = (q: DimensionQuestion) => (action: Parameters<typeof api.reviewEntity>[3]) =>
    run(`dim-${q.id}`, () => api.reviewEntity(doc.id, "dimension", q.id, action));

  return (
    <div className="space-y-5">
      <Panel
        title="Causality investigation"
        subtitle="The evidence organised into the dimensions that drive a causality judgment. The AI proposes an answer for each; you confirm or correct it."
        aside={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              tone={doc.dimensions.length ? "ghost" : "primary"}
              busy={busyKey === "suggest-dimensions"}
              onClick={() => suggest("dimensions")}
            >
              {doc.dimensions.length ? "Re-run analysis" : "✨ Analyse dimensions"}
            </Button>
            {stats.dimensions_pending > 0 && (
              <Button
                size="sm"
                busy={busyKey === "bulk-dimensions"}
                onClick={() =>
                  run("bulk-dimensions", () =>
                    api.bulkReview(doc.id, {
                      entity_type: "dimension",
                      status: "REVIEWER_ACCEPTED",
                    }),
                  )
                }
              >
                Accept all pending
              </Button>
            )}
          </div>
        }
      >
        {doc.dimensions.length === 0 ? (
          <EmptyState>
            Nothing analysed yet. This step breaks the case into temporality, dechallenge,
            rechallenge and dose relationship, so each can be judged separately rather than
            collapsed into one verdict.
          </EmptyState>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Pill tone="support">
              {stats.dimensions_total - stats.dimensions_pending} confirmed
            </Pill>
            <Pill tone={stats.dimensions_pending ? "unknown" : "neutral"}>
              {stats.dimensions_pending} awaiting review
            </Pill>
          </div>
        )}
      </Panel>

      {doc.dimensions.length > 0 &&
        ORDER.map((dimension) => {
          const questions = forDimension(dimension);
          if (!questions.length) return null;
          const pending = questions.filter((q) => isPending(q.reviewer_status)).length;
          return (
            <Panel
              key={dimension}
              title={DIMENSION_LABELS[dimension]}
              subtitle={GUIDANCE[dimension]}
              aside={
                pending > 0 ? (
                  <Pill tone="unknown">{pending} to review</Pill>
                ) : (
                  <Pill tone="support">reviewed</Pill>
                )
              }
            >
              <ul className="space-y-2">
                {questions.map((q) => (
                  <ReviewableCard
                    key={q.id}
                    item={q}
                    title={DIMENSION_LABELS[dimension]}
                    subtitle={q.question}
                    activeSpanId={active?.sourceId}
                    onSelectSpan={onSelectSpan}
                    onReview={review(q)}
                    busy={busyKey === `dim-${q.id}`}
                    editLabel="Change answer"
                  />
                ))}
              </ul>
            </Panel>
          );
        })}

      {doc.dimensions.length > 0 && (
        <Callout tone="accent" title="Alternative etiologies">
          {GUIDANCE.ALTERNATIVE_ETIOLOGIES}
        </Callout>
      )}
    </div>
  );
}
