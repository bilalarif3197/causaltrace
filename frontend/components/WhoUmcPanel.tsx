"use client";

import type { ActiveSpan, WhoUmcResult } from "@/lib/types";
import { AnswerChip, EvidenceBullet, Panel, Pill } from "./ui";

/**
 * Kept visually distinct from the Naranjo panel on purpose. Naranjo produces a
 * reproducible arithmetic score; WHO-UMC is a category judgement. Styling them
 * identically would imply the two carry the same kind of authority.
 */
export default function WhoUmcPanel({
  result,
  active,
  onSelect,
}: {
  result: WhoUmcResult;
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  return (
    <Panel
      title="WHO-UMC assessment"
      subtitle="A structured category judgement, not an arithmetic score."
      aside={<Pill tone="neutral" className="shrink-0 !text-indigo-300 !border-indigo-400/40 !bg-indigo-400/10">{result.classification}</Pill>}
      className="border-indigo-400/25 bg-indigo-950/10"
    >
      <p className="text-[12.5px] leading-relaxed text-slate-soft">{result.reasoning}</p>

      {result.criteria.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
            Criteria
          </h3>
          <ul className="space-y-1.5">
            {result.criteria.map((c) => (
              <li
                key={c.criterion}
                className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-lg bg-ink-850/50 px-3 py-2"
              >
                <span className="shrink-0">
                  <AnswerChip answer={c.met} />
                </span>
                <span className="flex-1 min-w-[12rem]">
                  <p className="text-[12.5px] leading-snug text-slate-soft">{c.criterion}</p>
                  {c.note && (
                    <p className="mt-0.5 text-[11px] leading-relaxed text-slate-muted">{c.note}</p>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.supporting_evidence.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
            Cited evidence
          </h3>
          <ul className="space-y-1.5">
            {result.supporting_evidence.map((item) => {
              const isActive = active?.sourceId === item.id;
              return (
                <EvidenceBullet
                  key={item.id}
                  valence="support"
                  statement={item.statement}
                  span={item.span}
                  isActive={isActive}
                  onSelect={() =>
                    onSelect(
                      isActive
                        ? null
                        : { span: item.span!, sourceId: item.id, label: item.statement },
                    )
                  }
                />
              );
            })}
          </ul>
        </div>
      )}

      {result.major_uncertainty && (
        <div className="mt-5 rounded-lg border border-unknown-400/35 bg-unknown-bg px-4 py-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-unknown-400">
            Major uncertainty
          </h3>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-soft">
            {result.major_uncertainty}
          </p>
        </div>
      )}
    </Panel>
  );
}
