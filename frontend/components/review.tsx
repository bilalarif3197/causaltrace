"use client";

import { useEffect, useRef, useState } from "react";
import {
  confirmedValue,
  isPending,
  STATUS_META,
  type ActiveSpan,
  type ReviewableBase,
  type ReviewerStatus,
  type Verdict,
} from "@/lib/review";
import { Button, Pill, inputClass } from "./ui";

/* --------------------------------------------------------------------------
   Status
   -------------------------------------------------------------------------- */

/**
 * The state badge. Carries a glyph, a word and a colour — three channels, so
 * the meaning survives colour-blindness and greyscale printing. Reviewers make
 * decisions off these.
 */
export function StatusChip({ status, className = "" }: { status: ReviewerStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${meta.ring} ${meta.tone} ${className}`}
    >
      <span aria-hidden>{meta.glyph}</span>
      {meta.label}
    </span>
  );
}

export function VerificationBadge({ verdict, reason }: { verdict: Verdict; reason?: string | null }) {
  if (verdict === "SUPPORTED") {
    return (
      <Pill tone="support" title={reason ?? undefined}>
        ✓ evidence verified
      </Pill>
    );
  }
  const tone = verdict === "NOT_SUPPORTED" ? "against" : "unknown";
  const label = verdict === "NOT_SUPPORTED" ? "✕ evidence does not support this" : "~ partially supported";
  return (
    <Pill tone={tone} title={reason ?? undefined}>
      {label}
    </Pill>
  );
}

/* --------------------------------------------------------------------------
   Evidence
   -------------------------------------------------------------------------- */

/** Clickable verbatim quote that highlights its span in the source panel. */
export function SourceQuote({
  item,
  isActive,
  onSelect,
}: {
  item: ReviewableBase;
  isActive?: boolean;
  onSelect?: () => void;
}) {
  const span = item.ai?.span ?? null;
  const quote = item.ai?.evidence_text ?? null;
  if (!quote) return null;

  const locatable = span?.start != null;
  return (
    <button
      type="button"
      onClick={locatable ? onSelect : undefined}
      aria-disabled={!locatable}
      className={`mt-1.5 block w-full truncate text-left font-mono text-[11px] transition ${
        isActive ? "text-accent-400" : "text-accent-400/70 hover:text-accent-400"
      } ${locatable ? "cursor-pointer underline decoration-dotted underline-offset-2" : "cursor-default text-against-400/80 line-through"}`}
      title={locatable ? "Show in source narrative" : "This quote is not present in the narrative"}
    >
      “{quote}”
    </button>
  );
}

/* --------------------------------------------------------------------------
   Review controls
   -------------------------------------------------------------------------- */

export interface ReviewAction {
  status?: ReviewerStatus;
  value?: string | null;
  note?: string | null;
}

/**
 * Accept / Edit / Reject. Editing opens an inline field seeded with the AI's
 * value; saving records MODIFIED with the reviewer's text, which is stored
 * separately from the suggestion so both survive in the audit trail.
 */
export function ReviewControls({
  item,
  onReview,
  busy,
  editLabel = "Edit",
  compact = false,
}: {
  item: ReviewableBase;
  onReview: (action: ReviewAction) => void;
  busy?: boolean;
  editLabel?: string;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const startEdit = () => {
    setDraft(confirmedValue(item) ?? item.ai?.value ?? "");
    setEditing(true);
  };

  const save = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onReview({ status: "REVIEWER_MODIFIED", value: trimmed });
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
          className={`${inputClass} flex-1 min-w-[12rem]`}
        />
        <Button size="sm" tone="primary" onClick={save} busy={busy}>
          Save
        </Button>
        <Button size="sm" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
    );
  }

  const decided = !isPending(item.reviewer_status);

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${compact ? "" : "mt-2"}`}>
      <Button
        size="sm"
        tone="success"
        busy={busy}
        onClick={() => onReview({ status: "REVIEWER_ACCEPTED" })}
        title="Confirm this as reviewed evidence"
      >
        ✓ Accept
      </Button>
      <Button size="sm" onClick={startEdit} busy={busy} title="Correct the value">
        ✎ {editLabel}
      </Button>
      <Button
        size="sm"
        tone="danger"
        busy={busy}
        onClick={() => onReview({ status: "REVIEWER_REJECTED" })}
        title="Exclude this from the assessment"
      >
        ✕ Reject
      </Button>
      {decided && (
        <button
          type="button"
          onClick={() => onReview({ status: "AI_SUGGESTED" })}
          className="ml-1 text-[10.5px] text-slate-muted underline decoration-dotted underline-offset-2 hover:text-slate-soft"
          title="Undo this decision and return the item to the AI suggestion"
        >
          undo
        </button>
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------
   The standard reviewable card
   -------------------------------------------------------------------------- */

export function ReviewableCard({
  item,
  title,
  subtitle,
  activeSpanId,
  onSelectSpan,
  onReview,
  busy,
  children,
  editLabel,
}: {
  item: ReviewableBase & { id?: string };
  title: string;
  subtitle?: string;
  activeSpanId?: string | null;
  onSelectSpan?: (a: ActiveSpan | null) => void;
  onReview: (action: ReviewAction) => void;
  busy?: boolean;
  children?: React.ReactNode;
  editLabel?: string;
}) {
  const value = confirmedValue(item);
  const rejected = item.reviewer_status === "REVIEWER_REJECTED";
  const flagged = item.ai?.verification && item.ai.verification !== "SUPPORTED";
  const id = item.id ?? title;
  const isActive = activeSpanId === id;

  const select = () => {
    const span = item.ai?.span;
    if (!span || span.start == null || !onSelectSpan) return;
    onSelectSpan(isActive ? null : { span, sourceId: id, label: title });
  };

  return (
    <li
      className={`rounded-lg border px-3.5 py-3 transition ${
        rejected
          ? "border-ink-700/60 bg-ink-900/40 opacity-60"
          : isActive
            ? "border-accent-500/60 bg-accent-500/5"
            : flagged
              ? "border-unknown-400/40 bg-unknown-bg/40"
              : "border-ink-700/60 bg-ink-850/40"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-muted">{title}</span>
        <StatusChip status={item.reviewer_status} />
        {item.origin === "REVIEWER" && <Pill tone="accent">reviewer-added</Pill>}
        {item.ai?.verification && (
          <VerificationBadge verdict={item.ai.verification} reason={item.ai.verification_reason} />
        )}
      </div>

      {subtitle && <p className="mt-1.5 text-[12.5px] leading-snug text-slate-soft">{subtitle}</p>}

      {/* AI suggestion and reviewer value shown side by side, never merged. */}
      <div className="mt-2 space-y-1.5">
        {item.ai?.value && (
          <p className="text-[13px] leading-snug">
            <span className="mr-1.5 text-[10px] uppercase tracking-wider text-violet-300">
              AI suggested
            </span>
            <span className={rejected ? "text-slate-muted line-through" : "text-slate-soft"}>
              {item.ai.value}
            </span>
          </p>
        )}
        {value && value !== item.ai?.value && (
          <p className="text-[13px] leading-snug">
            <span className="mr-1.5 text-[10px] uppercase tracking-wider text-accent-400">
              Reviewer
            </span>
            <span className="text-slate-soft">{value}</span>
          </p>
        )}
        {!item.ai?.value && !value && (
          <p className="text-[12.5px] italic text-slate-muted">No value recorded.</p>
        )}
      </div>

      {item.ai?.rationale && (
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-muted">{item.ai.rationale}</p>
      )}

      <SourceQuote item={item} isActive={isActive} onSelect={select} />

      {flagged && item.ai?.verification_reason && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-unknown-400">
          Verifier: {item.ai.verification_reason}
        </p>
      )}

      {item.reviewer_note && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-accent-400/80">
          Note: {item.reviewer_note}
        </p>
      )}

      {children}

      <ReviewControls item={item} onReview={onReview} busy={busy} editLabel={editLabel} />
    </li>
  );
}

/* --------------------------------------------------------------------------
   Source narrative with highlighting
   -------------------------------------------------------------------------- */

/**
 * Highlighting works off character offsets resolved server-side, not by
 * re-searching in the browser. The backend already decided whether a quote
 * genuinely occurs in the source, so the UI cannot "find" a match the
 * pipeline rejected.
 */
export function SourcePanel({
  narrative,
  active,
  onClear,
  className = "",
}: {
  narrative: string;
  active: ActiveSpan | null;
  onClear: () => void;
  className?: string;
}) {
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (markRef.current) markRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  let content: React.ReactNode = narrative;
  const span = active?.span;
  if (span && span.start != null && span.end != null) {
    const start = Math.max(0, Math.min(span.start, narrative.length));
    const end = Math.max(start, Math.min(span.end, narrative.length));
    content = (
      <>
        {narrative.slice(0, start)}
        <mark ref={markRef} className="evidence-active">
          {narrative.slice(start, end)}
        </mark>
        {narrative.slice(end)}
      </>
    );
  }

  return (
    <section
      className={`rounded-xl border border-ink-700/70 bg-ink-900/60 ${className}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-ink-700/60 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-soft">
            Source narrative
          </h2>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-muted">
            {active
              ? "Highlighted text is the exact span cited for the selected item."
              : "Click any quoted evidence to trace it back to the source."}
          </p>
        </div>
        {active && (
          <button
            type="button"
            onClick={onClear}
            className="shrink-0 rounded-md border border-ink-600 px-2 py-1 text-[10.5px] text-slate-muted transition hover:border-accent-600/60 hover:text-accent-400"
          >
            Clear
          </button>
        )}
      </header>

      {active?.label && (
        <div className="border-b border-ink-700/60 bg-ink-850/50 px-4 py-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-muted">Tracing</p>
          <p className="mt-0.5 text-[12px] text-slate-soft">{active.label}</p>
          {active.span.locator !== "exact" && (
            <p className="mt-1 text-[10.5px] text-unknown-400">
              Matched via {active.span.locator} alignment — the citation was not
              character-for-character identical to the source.
            </p>
          )}
        </div>
      )}

      <div className="max-h-[calc(100vh-15rem)] overflow-y-auto px-4 py-3.5">
        <article className="whitespace-pre-wrap text-[13px] leading-[1.85] text-slate-soft/90">
          {content}
        </article>
      </div>
    </section>
  );
}
