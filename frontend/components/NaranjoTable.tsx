"use client";

import type { ActiveSpan, NaranjoResult } from "@/lib/types";
import { AnswerChip, Panel, Pill } from "./ui";

const MIN = -4;
const MAX = 13;
const pct = (v: number) => ((Math.max(MIN, Math.min(MAX, v)) - MIN) / (MAX - MIN)) * 100;

const BANDS = [
  { name: "Doubtful", from: MIN, to: 0 },
  { name: "Possible", from: 1, to: 4 },
  { name: "Probable", from: 5, to: 8 },
  { name: "Definite", from: 9, to: MAX },
];

/**
 * Shows where the total sits on the -4..+13 scale, and -- more importantly --
 * the span the total could occupy if the UNKNOWN items were resolved. A narrow
 * span means the classification is robust; a span crossing band boundaries
 * means the headline label is an artefact of missing data.
 */
function ScoreScale({ result }: { result: NaranjoResult }) {
  const left = pct(result.score_floor);
  const width = Math.max(0.8, pct(result.score_ceiling) - left);

  return (
    <div>
      <div className="relative h-11">
        {/* Band backdrop */}
        <div className="absolute inset-x-0 top-3 flex h-3 overflow-hidden rounded-full border border-ink-700">
          {BANDS.map((b) => (
            <div
              key={b.name}
              style={{ width: `${((b.to - b.from + 1) / (MAX - MIN + 1)) * 100}%` }}
              className="border-r border-ink-900/80 bg-ink-800 last:border-r-0"
              title={`${b.name} (${b.from} to ${b.to})`}
            />
          ))}
        </div>
        {/* Possible range given unknowns */}
        <div
          className="absolute top-3 h-3 rounded-full bg-unknown-400/30 ring-1 ring-unknown-400/50"
          style={{ left: `${left}%`, width: `${width}%` }}
          title={`Could fall between ${result.score_floor} and ${result.score_ceiling}`}
        />
        {/* Actual total */}
        <div className="absolute top-1.5 -translate-x-1/2" style={{ left: `${pct(result.total_score)}%` }}>
          <div className="h-6 w-0.5 bg-accent-400" />
          <div className="mx-auto mt-0.5 h-1.5 w-1.5 rotate-45 bg-accent-400" />
        </div>
      </div>
      <div className="flex justify-between font-mono text-[10px] text-slate-muted">
        {BANDS.map((b) => (
          <span key={b.name}>{b.name}</span>
        ))}
      </div>
    </div>
  );
}

export default function NaranjoTable({
  result,
  active,
  onSelect,
}: {
  result: NaranjoResult;
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  return (
    <Panel
      title="Naranjo ADR probability scale"
      subtitle="Each item answered independently from the narrative; the total is computed in code, not by the model."
      aside={
        <div className="shrink-0 text-right">
          <p className="font-mono text-2xl font-semibold leading-none text-accent-400">
            {result.total_score > 0 ? `+${result.total_score}` : result.total_score}
          </p>
          <p className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-soft">
            {result.classification}
          </p>
        </div>
      }
    >
      <div className="mb-5">
        <ScoreScale result={result} />
      </div>

      {!result.classification_is_stable && (
        <div className="mb-5 rounded-lg border border-unknown-400/40 bg-unknown-bg px-4 py-3">
          <p className="text-[12px] font-semibold text-unknown-400">
            This classification is not stable.
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-soft">
            {result.unknown_count} of 10 items are UNKNOWN. Depending on how they resolved, the
            total could fall anywhere from{" "}
            <span className="font-mono">{result.score_floor}</span> to{" "}
            <span className="font-mono">{result.score_ceiling}</span> — spanning{" "}
            <span className="font-semibold">
              {
                new Set(
                  BANDS.filter(
                    (b) => b.to >= result.score_floor && b.from <= result.score_ceiling,
                  ).map((b) => b.name),
                ).size
              }{" "}
              classification bands
            </span>
            . Treat the headline label as provisional.
          </p>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-ink-700 text-[10px] uppercase tracking-[0.12em] text-slate-muted">
              <th className="w-8 pb-2 pr-2 font-medium">#</th>
              <th className="pb-2 pr-3 font-medium">Item</th>
              <th className="w-28 pb-2 pr-3 font-medium">Answer</th>
              <th className="w-14 pb-2 pr-3 text-right font-medium">Score</th>
              <th className="pb-2 font-medium">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {result.items.map((item) => {
              const clickable = item.span?.start != null;
              const rowId = `naranjo-${item.number}`;
              const isActive = active?.sourceId === rowId;
              return (
                <tr
                  key={item.number}
                  className={`border-b border-ink-800/70 align-top transition ${
                    isActive ? "bg-accent-500/10" : "hover:bg-ink-850/50"
                  }`}
                >
                  <td className="py-2.5 pr-2 font-mono text-[11px] text-slate-muted">
                    {item.number}
                  </td>
                  <td className="py-2.5 pr-3">
                    <p className="text-[12.5px] leading-snug text-slate-soft">{item.question}</p>
                    {item.commonly_unknown && item.answer === "UNKNOWN" && (
                      <p className="mt-1 text-[10.5px] text-slate-muted">
                        Unknown in &gt;85% of real cases
                      </p>
                    )}
                    {item.rationale && (
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-muted">
                        {item.rationale}
                      </p>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    <AnswerChip answer={item.answer} />
                    {item.verdict === "NOT_SUPPORTED" && (
                      <p className="mt-1 text-[10px] font-medium text-against-400">
                        citation rejected → reset to UNKNOWN
                      </p>
                    )}
                    {item.verdict === "PARTIALLY_SUPPORTED" && (
                      <p className="mt-1 text-[10px] text-unknown-400">citation ambiguous</p>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono text-[12px]">
                    <span
                      className={
                        item.score > 0
                          ? "text-support-400"
                          : item.score < 0
                            ? "text-against-400"
                            : "text-slate-muted"
                      }
                    >
                      {item.score > 0 ? `+${item.score}` : item.score}
                    </span>
                  </td>
                  <td className="py-2.5">
                    {clickable ? (
                      <button
                        type="button"
                        onClick={() =>
                          onSelect(
                            isActive
                              ? null
                              : {
                                  span: item.span!,
                                  sourceId: rowId,
                                  label: `Naranjo item ${item.number}: ${item.question}`,
                                },
                          )
                        }
                        className="max-w-[22rem] text-left font-mono text-[11px] leading-relaxed text-accent-400/80 underline decoration-dotted underline-offset-2 transition hover:text-accent-400"
                      >
                        “{item.span!.text}”
                      </button>
                    ) : (
                      <span className="text-[11px] italic text-slate-muted">Not reported</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3} className="pt-3 text-[11px] uppercase tracking-wider text-slate-muted">
                Deterministic total
              </td>
              <td className="pt-3 text-right font-mono text-[13px] font-semibold text-accent-400">
                {result.total_score > 0 ? `+${result.total_score}` : result.total_score}
              </td>
              <td className="pt-3">
                <Pill tone="accent">{result.classification}</Pill>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="mt-4 border-t border-ink-700/60 pt-3 text-[11px] leading-relaxed text-slate-muted">
        Scale range −4 to +13. Definite ≥9, probable 5–8, possible 1–4, doubtful ≤0. Weights follow
        the published Naranjo worksheet. Item 6 (placebo) is scored UNKNOWN rather than NO when no
        placebo was given, since scoring it NO would add a point for something that never happened.
      </p>
    </Panel>
  );
}
