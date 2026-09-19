"use client";

import type { ActiveSpan, EvidenceItem, Hypothesis } from "@/lib/types";
import { EvidenceBullet, Panel, SupportMeter, VALENCE_LABEL, ValenceIcon, type Valence } from "./ui";

function Bucket({
  valence,
  items,
  active,
  onSelect,
  emptyNote,
}: {
  valence: Valence;
  items: EvidenceItem[];
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
  emptyNote: string;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <ValenceIcon valence={valence} className="h-4 w-4" />
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
          {VALENCE_LABEL[valence]}
        </h3>
        <span className="font-mono text-[11px] text-slate-muted">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-ink-700 px-3 py-2.5 text-[12px] italic text-slate-muted">
          {emptyNote}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => {
            const isActive = active?.sourceId === item.id;
            return (
              <EvidenceBullet
                key={item.id}
                valence={valence}
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
      )}
    </div>
  );
}

export default function HypothesisPanel({
  hypothesis,
  active,
  onSelect,
}: {
  hypothesis: Hypothesis | null;
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  if (!hypothesis) {
    return (
      <Panel title="Evidence inspector">
        <p className="text-sm text-slate-muted">
          Select a hypothesis in the graph to see what supports it, what argues against it, and what
          the narrative never reported.
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title="Evidence for this hypothesis"
      subtitle={hypothesis.hypothesis}
      aside={<SupportMeter label={hypothesis.support_label} />}
    >
      {hypothesis.label_rationale && (
        <p className="mb-4 rounded-lg border-l-2 border-accent-600/60 bg-ink-850/60 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-slate-soft">
          {hypothesis.label_rationale}
        </p>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <Bucket
          valence="support"
          items={hypothesis.supporting_evidence}
          active={active}
          onSelect={onSelect}
          emptyNote="Nothing in the narrative supports this hypothesis."
        />
        <Bucket
          valence="against"
          items={hypothesis.contradicting_evidence}
          active={active}
          onSelect={onSelect}
          emptyNote="Nothing in the narrative argues against this hypothesis — which is not the same as evidence for it."
        />
        <Bucket
          valence="unknown"
          items={hypothesis.unknown_evidence}
          active={active}
          onSelect={onSelect}
          emptyNote="No decisive missing information identified."
        />
      </div>
    </Panel>
  );
}
