"use client";

import * as api from "@/lib/api";
import type { Answer, FrameworkResult, LabelEvidence } from "@/lib/review";
import { AiIcon, Button, Callout, Panel, Pill } from "../ui";
import { SourceQuote, StatusChip } from "../review";
import type { StepProps } from "./types";

const MIN = -4;
const MAX = 13;
const pct = (v: number) => ((Math.max(MIN, Math.min(MAX, v)) - MIN) / (MAX - MIN)) * 100;

const BANDS = [
  { name: "Doubtful", from: MIN, to: 0 },
  { name: "Possible", from: 1, to: 4 },
  { name: "Probable", from: 5, to: 8 },
  { name: "Definite", from: 9, to: MAX },
];

function ScoreScale({ result }: { result: FrameworkResult }) {
  const left = pct(result.score_floor);
  const width = Math.max(0.8, pct(result.score_ceiling) - left);
  // Bands are unequal (5/4/4/5 of 18 units), so labels must use the same
  // proportional widths as the bars. `justify-between` spaced them evenly and
  // put every label under the wrong band.
  const bandWidth = (b: (typeof BANDS)[number]) => ((b.to - b.from + 1) / (MAX - MIN + 1)) * 100;

  return (
    <div>
      <div className="relative h-9">
        <div className="absolute inset-x-0 top-3 flex h-3 overflow-hidden rounded-full border border-ink-700">
          {BANDS.map((b) => (
            <div
              key={b.name}
              style={{ width: `${bandWidth(b)}%` }}
              className="border-r border-ink-900/80 bg-ink-800 last:border-r-0"
              title={`${b.name} (${b.from} to ${b.to})`}
            />
          ))}
        </div>
        <div
          className="absolute top-3 h-3 rounded-full bg-unknown-400/30 ring-1 ring-unknown-400/50"
          style={{ left: `${left}%`, width: `${width}%` }}
          title={`Could fall between ${result.score_floor} and ${result.score_ceiling}`}
        />
        <div
          className="absolute top-1 -translate-x-1/2"
          style={{ left: `${pct(result.total_score)}%` }}
          title={`Total ${result.total_score}`}
        >
          <div className="h-7 w-0.5 bg-accent-400" />
        </div>
      </div>
      <div className="flex text-[10px] text-slate-muted">
        {BANDS.map((b) => (
          <span key={b.name} style={{ width: `${bandWidth(b)}%` }} className="text-center">
            {b.name}
          </span>
        ))}
      </div>
    </div>
  );
}

const ANSWERS: Answer[] = ["YES", "NO", "UNKNOWN"];

/**
 * Evidence for item 1, retrieved from the actual FDA label.
 *
 * Before this existed, item 1 ("previous conclusive reports") was answered
 * from the model's own memory with no source. The panel is careful about what
 * the label does and does not license, and it never fills the answer in.
 */
function LabelEvidencePanel({
  evidence,
  onLookup,
  busy,
}: {
  evidence: LabelEvidence | null;
  onLookup: () => void;
  busy: boolean;
}) {
  const verdict =
    evidence == null || !evidence.label_found
      ? null
      : evidence.mentions_event === true
        ? { tone: "support" as const, text: "This reaction appears on the label" }
        : evidence.mentions_event === false
          ? { tone: "unknown" as const, text: "Not listed on this label" }
          : { tone: "unknown" as const, text: "Label retrieved; coverage unclear" };

  return (
    <Panel
      title="Known-reaction evidence"
      subtitle="Item 1 asks about previous conclusive reports. This retrieves the current FDA label so your answer can cite text rather than recollection."
      aside={
        <Button size="sm" busy={busy} onClick={onLookup}>
          {evidence ? "Re-check label" : "Look up FDA label"}
        </Button>
      }
    >
      {!evidence ? (
        <p className="text-[12.5px] leading-relaxed text-slate-muted">
          Not looked up yet. Without it, item 1 rests on the model&rsquo;s own memory — which is
          exactly the kind of unverifiable claim this workspace is built to avoid.
        </p>
      ) : !evidence.label_found ? (
        <Callout tone="unknown" title="No label available">
          {evidence.unavailable_reason}
        </Callout>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {verdict && <Pill tone={verdict.tone}>{verdict.text}</Pill>}
            {evidence.citation.generic_names?.[0] && (
              <Pill tone="neutral">{evidence.citation.generic_names[0]}</Pill>
            )}
            {evidence.citation.effective_time && (
              <span className="font-mono text-[10.5px] text-slate-muted">
                label rev. {evidence.citation.effective_time}
              </span>
            )}
          </div>

          {evidence.quote && (
            <blockquote className="rounded-lg border-l-2 border-support-400/60 bg-ink-850/60 px-3 py-2">
              <p className="font-mono text-[12px] leading-relaxed text-slate-soft">
                &ldquo;{evidence.quote}&rdquo;
              </p>
              <footer className="mt-1.5 text-[10.5px] text-slate-muted">
                {evidence.section ? `${evidence.section} section` : "FDA label"}
                {evidence.span?.locator === "exact" && " · verbatim match confirmed"}
                {evidence.citation.url && (
                  <>
                    {" · "}
                    <a
                      href={evidence.citation.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent-400 underline underline-offset-2"
                    >
                      view label on DailyMed
                    </a>
                  </>
                )}
              </footer>
            </blockquote>
          )}

          {evidence.reasoning && (
            <p className="text-[11.5px] leading-relaxed text-slate-muted">{evidence.reasoning}</p>
          )}

          <Callout tone="ai" title="What this does and does not establish">
            {evidence.CAVEAT}
          </Callout>
        </div>
      )}
    </Panel>
  );
}

export default function NaranjoReview({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc, stats, framework } = envelope;
  if (!framework) return null;

  const bandsSpanned = new Set(
    BANDS.filter((b) => b.to >= framework.score_floor && b.from <= framework.score_ceiling).map(
      (b) => b.name,
    ),
  ).size;

  return (
    <div className="space-y-5">
      <Panel
        title="Naranjo framework result"
        subtitle="Computed in application code from YOUR answers, not the model's. The AI's suggestion sits beside each item and never enters the arithmetic."
        aside={
          <div className="flex items-center gap-3">
            <div className="text-right">
              <p className="font-mono text-2xl font-semibold leading-none text-accent-400">
                {framework.total_score > 0 ? `+${framework.total_score}` : framework.total_score}
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-soft">
                {framework.classification}
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Button
                size="sm"
                tone={doc.naranjo.some((i) => i.ai_answer) ? "ghost" : "primary"}
                busy={busyKey === "suggest-naranjo"}
                onClick={() => suggest("naranjo")}
              >
                <AiIcon className="h-3 w-3" />
                Suggest answers
              </Button>
              {stats.naranjo_pending > 0 && (
                <Button
                  size="sm"
                  busy={busyKey === "bulk-naranjo"}
                  onClick={() =>
                    run("bulk-naranjo", () =>
                      api.bulkReview(doc.id, {
                        entity_type: "naranjo",
                        status: "REVIEWER_ACCEPTED",
                      }),
                    )
                  }
                >
                  Accept all AI answers
                </Button>
              )}
            </div>
          </div>
        }
      >
        <ScoreScale result={framework} />

        <div className="mt-4 space-y-3">
          {framework.unreviewed_count > 0 && (
            <Callout tone="ai" title="This is not your assessment yet">
              {framework.unreviewed_count} of 10 items have not been reviewed by you, so they
              score zero regardless of what the AI suggested. The total below reflects only the
              answers you have confirmed.
            </Callout>
          )}

          {!framework.classification_is_stable && (
            <Callout tone="unknown" title="Classification is not stable">
              {framework.unknown_count} item(s) are UNKNOWN. Depending on how they resolved, the
              total could fall anywhere from{" "}
              <span className="font-mono">{framework.score_floor}</span> to{" "}
              <span className="font-mono">{framework.score_ceiling}</span> — spanning{" "}
              <strong>{bandsSpanned} classification bands</strong>. Treat the label as
              provisional.
            </Callout>
          )}

          <p className="text-[11px] leading-relaxed text-slate-muted">
            This is a <strong className="text-slate-soft">framework result</strong>, not a final
            causality decision. You make that on the Conclusion step, and you are free to depart
            from this number.
          </p>
        </div>
      </Panel>

      <LabelEvidencePanel
        evidence={doc.label_evidence}
        busy={busyKey === "label"}
        onLookup={() => run("label", async () => (await api.lookupLabel(doc.id)).envelope)}
      />

      <Panel title="Items" bodyClassName="p-0">
        <ul className="divide-y divide-ink-800/70">
          {doc.naranjo.map((item) => {
            const key = `nar-${item.number}`;
            const isActive = active?.sourceId === `naranjo-${item.number}`;
            const disagrees =
              item.ai_answer && item.reviewer_status.startsWith("REVIEWER") && item.reviewer_answer !== item.ai_answer;
            return (
              <li key={item.number} className={`px-4 py-3 ${isActive ? "bg-accent-500/5" : ""}`}>
                <div className="flex flex-wrap items-start gap-3">
                  <span className="mt-0.5 font-mono text-[11px] text-slate-muted">
                    {item.number}
                  </span>
                  <div className="min-w-[14rem] flex-1">
                    <p className="text-[12.5px] leading-snug text-slate-soft">{item.question}</p>
                    {item.number === 1 && doc.label_evidence?.label_found && (
                      <p className="mt-1 text-[11px] text-support-400">
                        See the FDA label evidence above
                        {doc.label_evidence.mentions_event === true
                          ? " — this reaction is described on the label."
                          : doc.label_evidence.mentions_event === false
                            ? " — not listed there, which leaves this UNKNOWN rather than NO."
                            : "."}
                      </p>
                    )}
                    {item.commonly_unknown && item.reviewer_answer === "UNKNOWN" && (
                      <p className="mt-0.5 text-[10.5px] text-slate-muted">
                        Unknown in &gt;85% of real cases
                      </p>
                    )}
                    {item.ai && (
                      <p className="mt-1 text-[11px] text-violet-300">
                        <AiIcon className="h-2.5 w-2.5" />{" "}
                        AI suggests {item.ai_answer}
                        {item.ai.rationale ? ` — ${item.ai.rationale}` : ""}
                      </p>
                    )}
                    <SourceQuote
                      item={{
                        ai: item.ai,
                        reviewer_status: item.reviewer_status,
                        reviewer_value: null,
                        reviewer_note: item.reviewer_note,
                        origin: "AI",
                        reviewed_at: item.reviewed_at,
                      }}
                      isActive={isActive}
                      onSelect={() => {
                        const span = item.ai?.span;
                        if (!span || span.start == null) return;
                        onSelectSpan(
                          isActive
                            ? null
                            : {
                                span,
                                sourceId: `naranjo-${item.number}`,
                                label: `Naranjo item ${item.number}`,
                              },
                        );
                      }}
                    />
                  </div>

                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <div className="flex gap-1">
                      {ANSWERS.map((a) => (
                        <button
                          key={a}
                          type="button"
                          disabled={busyKey === key}
                          onClick={() =>
                            run(key, () =>
                              api.reviewEntity(doc.id, "naranjo", String(item.number), { value: a }),
                            )
                          }
                          className={`rounded-md border px-2 py-1 font-mono text-[10.5px] transition disabled:opacity-40 ${
                            item.reviewer_answer === a && item.reviewer_status.startsWith("REVIEWER")
                              ? a === "YES"
                                ? "border-support-400/60 bg-support-bg text-support-400"
                                : a === "NO"
                                  ? "border-against-400/60 bg-against-bg text-against-400"
                                  : "border-unknown-400/60 bg-unknown-bg text-unknown-400"
                              : "border-ink-600 text-slate-muted hover:border-accent-600/50 hover:text-slate-soft"
                          }`}
                        >
                          {a}
                        </button>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusChip status={item.reviewer_status} />
                      <span
                        className={`font-mono text-[12px] ${
                          item.score > 0
                            ? "text-support-400"
                            : item.score < 0
                              ? "text-against-400"
                              : "text-slate-muted"
                        }`}
                      >
                        {item.score > 0 ? `+${item.score}` : item.score}
                      </span>
                    </div>
                    {disagrees && <Pill tone="accent">overrides AI</Pill>}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="border-t border-ink-700/60 px-4 py-3">
          <p className="text-[11px] leading-relaxed text-slate-muted">
            Scale range −4 to +13. Definite ≥9, probable 5–8, possible 1–4, doubtful ≤0. Weights
            follow the published Naranjo worksheet. Item 6 (placebo) is scored UNKNOWN rather than
            NO when no placebo was given, since scoring it NO adds a point for something that
            never happened.
          </p>
        </div>
      </Panel>
    </div>
  );
}
