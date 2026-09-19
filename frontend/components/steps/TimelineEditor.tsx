"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import { isPending, type DateKind, type TimelineEntry } from "@/lib/review";
import { Button, Callout, EmptyState, Field, Panel, Pill, inputClass } from "../ui";
import { SourceQuote, StatusChip } from "../review";
import type { StepProps } from "./types";

const CATEGORY_DOT: Record<string, string> = {
  DRUG_START: "bg-accent-400",
  DRUG_STOP: "bg-slate-soft",
  DOSE_CHANGE: "bg-accent-600",
  EVENT_ONSET: "bg-against-400",
  LAB: "bg-sky-400",
  INFECTION: "bg-unknown-400",
  DIAGNOSIS: "bg-indigo-400",
  RECHALLENGE: "bg-fuchsia-400",
  RECOVERY: "bg-support-400",
  OTHER: "bg-ink-500",
};

const DATE_KINDS: { value: DateKind; label: string; hint: string }[] = [
  { value: "EXACT", label: "Exact", hint: "A specific date is stated" },
  { value: "APPROXIMATE", label: "Approximate", hint: "'late March', 'around day 10'" },
  { value: "RELATIVE", label: "Relative only", hint: "'five days later'" },
  { value: "UNKNOWN", label: "Unknown", hint: "Timing not stated" },
];

function EventRow({
  event,
  caseId,
  run,
  busyKey,
  active,
  onSelectSpan,
  total,
}: {
  event: TimelineEntry;
  caseId: string;
  run: StepProps["run"];
  busyKey: string | null;
  active: StepProps["active"];
  onSelectSpan: StepProps["onSelectSpan"];
  total: number;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(event.label);
  const [displayDate, setDisplayDate] = useState(event.display_date ?? "");
  const [kind, setKind] = useState<DateKind>(event.date_kind);

  const key = `evt-${event.id}`;
  const busy = busyKey === key;
  const isActive = active?.sourceId === event.id;

  const patch = (body: Parameters<typeof api.reviewEntity>[3]) =>
    run(key, () => api.reviewEntity(caseId, "event", event.id, body));

  const move = (delta: number) =>
    patch({ extra: { order_index: Math.max(1, Math.min(total, event.order_index + delta)) } });

  return (
    <li className="relative pl-7">
      <span
        className={`absolute left-0 top-3.5 h-[13px] w-[13px] rounded-full ring-4 ring-ink-900 ${
          CATEGORY_DOT[event.category] ?? CATEGORY_DOT.OTHER
        }`}
        aria-hidden
      />
      <div
        className={`rounded-lg border px-3 py-2.5 transition ${
          event.reviewer_status === "REVIEWER_REJECTED"
            ? "border-ink-700/60 bg-ink-900/40 opacity-60"
            : isActive
              ? "border-accent-500/60 bg-accent-500/5"
              : "border-ink-700/60 bg-ink-850/40"
        }`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] font-semibold text-accent-400">
            {event.display_date || event.relative_text || `Step ${event.order_index}`}
          </span>
          <StatusChip status={event.reviewer_status} />
          {event.timing_uncertain && (
            <Pill tone="unknown" title="Timing is approximate or not stated">
              timing uncertain
            </Pill>
          )}
          {event.origin === "REVIEWER" && <Pill tone="accent">reviewer-added</Pill>}
          <span className="ml-auto flex gap-1">
            <button
              type="button"
              onClick={() => move(-1)}
              disabled={busy || event.order_index <= 1}
              className="rounded border border-ink-600 px-1.5 text-[11px] text-slate-muted transition hover:text-accent-400 disabled:opacity-30"
              title="Move earlier"
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => move(1)}
              disabled={busy || event.order_index >= total}
              className="rounded border border-ink-600 px-1.5 text-[11px] text-slate-muted transition hover:text-accent-400 disabled:opacity-30"
              title="Move later"
            >
              ↓
            </button>
          </span>
        </div>

        {editing ? (
          <div className="mt-2.5 space-y-2.5">
            <Field label="Event">
              <input value={label} onChange={(e) => setLabel(e.target.value)} className={inputClass} />
            </Field>
            <div className="grid gap-2.5 sm:grid-cols-2">
              <Field label="Displayed timing">
                <input
                  value={displayDate}
                  onChange={(e) => setDisplayDate(e.target.value)}
                  placeholder="Mar 02"
                  className={inputClass}
                />
              </Field>
              <Field label="Timing certainty">
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as DateKind)}
                  className={inputClass}
                >
                  {DATE_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label} — {k.hint}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                tone="primary"
                busy={busy}
                onClick={async () => {
                  await patch({
                    status: "REVIEWER_MODIFIED",
                    value: label,
                    extra: { label, display_date: displayDate || null, date_kind: kind },
                  });
                  setEditing(false);
                }}
              >
                Save
              </Button>
              <Button size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            <p className="mt-1.5 text-[13px] leading-snug text-slate-soft">{event.label}</p>
            {event.relative_text && (
              <p className="mt-0.5 text-[11px] italic text-slate-muted">“{event.relative_text}”</p>
            )}
            <SourceQuote
              item={event}
              isActive={isActive}
              onSelect={() => {
                const span = event.ai?.span;
                if (!span || span.start == null) return;
                onSelectSpan(isActive ? null : { span, sourceId: event.id, label: event.label });
              }}
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Button
                size="sm"
                tone="success"
                busy={busy}
                onClick={() => patch({ status: "REVIEWER_ACCEPTED" })}
              >
                ✓ Accept
              </Button>
              <Button size="sm" onClick={() => setEditing(true)} busy={busy}>
                ✎ Edit
              </Button>
              <Button
                size="sm"
                tone="danger"
                busy={busy}
                onClick={() => run(key, () => api.deleteEvent(caseId, event.id))}
                title="Remove this event from the timeline"
              >
                ✕ Remove
              </Button>
            </div>
          </>
        )}
      </div>
    </li>
  );
}

export default function TimelineEditor({
  envelope,
  run,
  suggest,
  busyKey,
  active,
  onSelectSpan,
}: StepProps) {
  const { case: doc, stats } = envelope;
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [when, setWhen] = useState("");
  const [kind, setKind] = useState<DateKind>("UNKNOWN");

  const events = [...doc.timeline].sort((a, b) => a.order_index - b.order_index);
  const uncertain = events.filter((e) => e.timing_uncertain).length;

  return (
    <div className="space-y-5">
      <Panel
        title="Clinical timeline"
        subtitle="Built from the narrative. Reorder, correct the dates, or add events the AI missed."
        aside={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              tone={events.length ? "ghost" : "primary"}
              busy={busyKey === "suggest-timeline"}
              onClick={() => suggest("timeline")}
            >
              {events.length ? "Re-run timeline" : "✨ Build timeline"}
            </Button>
            {stats.timeline_pending > 0 && (
              <Button
                size="sm"
                busy={busyKey === "bulk-events"}
                onClick={() =>
                  run("bulk-events", () =>
                    api.bulkReview(doc.id, { entity_type: "event", status: "REVIEWER_ACCEPTED" }),
                  )
                }
              >
                Accept all pending
              </Button>
            )}
            <Button size="sm" onClick={() => setAdding((v) => !v)}>
              + Add event
            </Button>
          </div>
        }
      >
        {uncertain > 0 && (
          <div className="mb-4">
            <Callout tone="unknown" title="Timing is not fully determined">
              {uncertain} of {events.length} events have approximate or unstated timing. No
              calendar date is invented from vague wording — the original phrase is kept and the
              ordering is preserved instead.
            </Callout>
          </div>
        )}

        {adding && (
          <div className="mb-4 rounded-lg border border-accent-600/40 bg-accent-500/5 p-3">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <Field label="Event">
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Liver biopsy performed"
                  className={inputClass}
                />
              </Field>
              <Field label="Timing">
                <input
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                  placeholder="Mar 20"
                  className={inputClass}
                />
              </Field>
              <Field label="Certainty">
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as DateKind)}
                  className={inputClass}
                >
                  {DATE_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                tone="primary"
                disabled={!label.trim()}
                busy={busyKey === "add-event"}
                onClick={async () => {
                  await run("add-event", () =>
                    api.addEvent(doc.id, {
                      label: label.trim(),
                      display_date: when || null,
                      date_kind: kind,
                    }),
                  );
                  setLabel("");
                  setWhen("");
                  setAdding(false);
                }}
              >
                Add to timeline
              </Button>
              <Button size="sm" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {events.length === 0 ? (
          <EmptyState>
            No timeline yet. Build one from the narrative, or add events by hand.
          </EmptyState>
        ) : (
          <ol className="relative space-y-2">
            <div className="absolute left-[6px] top-3 bottom-3 w-px bg-ink-700" aria-hidden />
            {events.map((event) => (
              <EventRow
                key={event.id}
                event={event}
                caseId={doc.id}
                run={run}
                busyKey={busyKey}
                active={active}
                onSelectSpan={onSelectSpan}
                total={events.length}
              />
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}
