"use client";

import type { ActiveSpan, EventCategory, TimelineEvent } from "@/lib/types";
import { Panel, Pill } from "./ui";

/** Category styling. The dot glyph differentiates categories without colour. */
const CATEGORY: Record<EventCategory, { label: string; dot: string; ring: string }> = {
  DRUG_START: { label: "Drug start", dot: "bg-accent-400", ring: "ring-accent-400/30" },
  DRUG_STOP: { label: "Drug stop", dot: "bg-slate-soft", ring: "ring-slate-soft/20" },
  DOSE_CHANGE: { label: "Dose change", dot: "bg-accent-600", ring: "ring-accent-600/30" },
  EVENT_ONSET: { label: "Event onset", dot: "bg-against-400", ring: "ring-against-400/30" },
  LAB: { label: "Lab", dot: "bg-sky-400", ring: "ring-sky-400/30" },
  INFECTION: { label: "Infection", dot: "bg-unknown-400", ring: "ring-unknown-400/30" },
  DIAGNOSIS: { label: "Diagnostic", dot: "bg-indigo-400", ring: "ring-indigo-400/30" },
  RECHALLENGE: { label: "Rechallenge", dot: "bg-fuchsia-400", ring: "ring-fuchsia-400/30" },
  RECOVERY: { label: "Recovery", dot: "bg-support-400", ring: "ring-support-400/30" },
  OTHER: { label: "Other", dot: "bg-ink-500", ring: "ring-ink-500/30" },
};

export default function Timeline({
  events,
  active,
  onSelect,
}: {
  events: TimelineEvent[];
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  const inferredCount = events.filter((e) => e.date_certainty !== "EXACT").length;

  return (
    <Panel
      title="Reconstructed timeline"
      subtitle={`${events.length} events in chronological order`}
      aside={
        inferredCount > 0 ? (
          <Pill tone="unknown" className="shrink-0">
            {inferredCount} without an exact date
          </Pill>
        ) : undefined
      }
    >
      {events.length === 0 ? (
        <p className="text-sm text-slate-muted">No timeline events were extracted.</p>
      ) : (
        <ol className="relative space-y-1">
          {/* Spine */}
          <div className="absolute left-[7px] top-2 bottom-2 w-px bg-ink-700" aria-hidden />

          {events.map((event) => {
            const style = CATEGORY[event.category];
            const clickable = event.span?.start != null;
            const isActive = active?.sourceId === event.id;
            return (
              <li key={event.id} className="relative pl-7">
                <span
                  className={`absolute left-0 top-[11px] h-[15px] w-[15px] rounded-full ring-4 ${style.ring} ${style.dot}`}
                  aria-hidden
                />
                <button
                  type="button"
                  onClick={
                    clickable
                      ? () =>
                          onSelect(
                            isActive
                              ? null
                              : { span: event.span!, sourceId: event.id, label: event.label },
                          )
                      : undefined
                  }
                  aria-disabled={!clickable}
                  className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                    isActive
                      ? "border-accent-500/70 bg-accent-500/10"
                      : "border-transparent hover:border-ink-600 hover:bg-ink-850/60"
                  } ${clickable ? "cursor-pointer" : "cursor-default"}`}
                >
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <span className="font-mono text-[11px] font-semibold text-accent-400">
                      {event.display_date ?? `Step ${event.order}`}
                    </span>
                    <span className="text-[10px] uppercase tracking-wider text-slate-muted">
                      {style.label}
                    </span>
                    {event.date_certainty === "RELATIVE" && (
                      <span className="text-[10px] text-unknown-400">relative timing</span>
                    )}
                    {event.date_certainty === "UNKNOWN" && (
                      <span className="text-[10px] text-unknown-400">timing not stated</span>
                    )}
                  </div>
                  <p className="mt-1 text-[13px] leading-snug text-slate-soft">{event.label}</p>
                  {event.relative_text && (
                    <p className="mt-0.5 text-[11px] italic text-slate-muted">
                      “{event.relative_text}”
                    </p>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      )}

      <p className="mt-4 border-t border-ink-700/60 pt-3 text-[11px] leading-relaxed text-slate-muted">
        Relative ordering is always preserved. Where the narrative gives only relative timing, the
        original phrase is shown and no calendar date is inferred — including the year, which these
        narratives never state.
      </p>
    </Panel>
  );
}
