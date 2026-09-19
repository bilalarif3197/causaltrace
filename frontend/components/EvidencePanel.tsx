"use client";

import { useEffect, useMemo, useRef } from "react";
import type { ActiveSpan } from "@/lib/types";
import { Panel, Pill } from "./ui";

/**
 * The Evidence Inspector: the original narrative, with the span behind the
 * currently selected claim highlighted in place and scrolled into view.
 *
 * Highlighting works off character offsets resolved server-side by
 * `spans.locate_span`, not by re-searching the text in the browser. That
 * matters: the backend already decided whether a quote genuinely occurs in the
 * source, so the UI cannot accidentally "find" a match the pipeline rejected.
 */
export default function EvidencePanel({
  narrative,
  active,
  onClear,
}: {
  narrative: string;
  active: ActiveSpan | null;
  onClear: () => void;
}) {
  const markRef = useRef<HTMLElement | null>(null);

  const segments = useMemo(() => {
    const span = active?.span;
    if (!span || span.start == null || span.end == null) return null;
    const start = Math.max(0, Math.min(span.start, narrative.length));
    const end = Math.max(start, Math.min(span.end, narrative.length));
    return {
      before: narrative.slice(0, start),
      match: narrative.slice(start, end),
      after: narrative.slice(end),
    };
  }, [narrative, active]);

  useEffect(() => {
    if (markRef.current) {
      markRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [active]);

  return (
    <Panel
      title="Source narrative"
      subtitle={
        active
          ? "Highlighted text is the exact span cited for the selected claim."
          : "Select any claim, hypothesis or Naranjo item to trace it back to its source text."
      }
      aside={
        active ? (
          <button
            type="button"
            onClick={onClear}
            className="shrink-0 rounded-md border border-ink-600 px-2 py-1 text-[11px] text-slate-muted transition hover:border-accent-600/60 hover:text-accent-400"
          >
            Clear highlight
          </button>
        ) : (
          <Pill tone="neutral">verbatim</Pill>
        )
      }
      bodyClassName="p-0"
    >
      {active?.label && (
        <div className="border-b border-ink-700/60 bg-ink-850/50 px-5 py-2.5">
          <p className="text-[11px] uppercase tracking-wider text-slate-muted">Tracing</p>
          <p className="mt-0.5 text-[13px] text-slate-soft">{active.label}</p>
          {active.span.locator !== "exact" && (
            <p className="mt-1.5 text-[11px] text-unknown-400">
              Matched via {active.span.locator} alignment (ratio {active.span.match_ratio}); the
              citation was not character-for-character identical to the source.
            </p>
          )}
        </div>
      )}
      <div className="max-h-[calc(100vh-19rem)] overflow-y-auto px-5 py-4">
        <article className="whitespace-pre-wrap text-[13.5px] leading-[1.85] text-slate-soft/90">
          {segments ? (
            <>
              {segments.before}
              <mark ref={markRef} className="evidence-active">
                {segments.match}
              </mark>
              {segments.after}
            </>
          ) : (
            narrative
          )}
        </article>
      </div>
    </Panel>
  );
}
