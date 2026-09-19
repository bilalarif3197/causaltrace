import type { ReactNode } from "react";
import type { Answer, SourceSpan, SupportLabel } from "@/lib/types";

/* ---------------------------------------------------------------------------
   Layout atoms
   --------------------------------------------------------------------------- */

export function Panel({
  title,
  subtitle,
  aside,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: string;
  subtitle?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-ink-700/70 bg-ink-900/60 backdrop-blur-sm ${className}`}
    >
      {title && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-700/60 px-5 py-3.5">
          <div>
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-slate-soft">
              {title}
            </h2>
            {subtitle && <p className="mt-1 text-xs text-slate-muted">{subtitle}</p>}
          </div>
          {aside}
        </header>
      )}
      <div className={bodyClassName || "p-5"}>{children}</div>
    </section>
  );
}

export function Pill({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "support" | "against" | "unknown";
  className?: string;
}) {
  const tones = {
    neutral: "border-ink-600 bg-ink-800/80 text-slate-soft",
    accent: "border-accent-600/60 bg-accent-500/10 text-accent-400",
    support: "border-support-400/40 bg-support-bg text-support-400",
    against: "border-against-400/40 bg-against-bg text-against-400",
    unknown: "border-unknown-400/40 bg-unknown-bg text-unknown-400",
  } as const;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   Evidence valence

   Every valence is conveyed three ways: an icon shape, a text label, and a
   colour. Removing any one of the three still leaves the meaning legible.
   --------------------------------------------------------------------------- */

export type Valence = "support" | "against" | "unknown";

export const VALENCE_LABEL: Record<Valence, string> = {
  support: "Supports",
  against: "Argues against",
  unknown: "Not reported",
};

export function ValenceIcon({ valence, className = "h-3.5 w-3.5" }: { valence: Valence; className?: string }) {
  if (valence === "support") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden className={`${className} text-support-400`} fill="currentColor">
        <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm3.2 4.9-3.9 4.2a.85.85 0 0 1-1.25.02L4.3 8.9a.85.85 0 0 1 1.2-1.2l1.13 1.13 3.32-3.57a.85.85 0 0 1 1.25 1.15Z" />
      </svg>
    );
  }
  if (valence === "against") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden className={`${className} text-against-400`} fill="currentColor">
        <path d="M7.13 1.94a1 1 0 0 1 1.74 0l6 10.56A1 1 0 0 1 14 14H2a1 1 0 0 1-.87-1.5l6-10.56ZM8 5.25a.8.8 0 0 0-.8.86l.22 2.94a.58.58 0 0 0 1.16 0l.22-2.94A.8.8 0 0 0 8 5.25Zm0 5.1a.85.85 0 1 0 0 1.7.85.85 0 0 0 0-1.7Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={`${className} text-unknown-400`} fill="currentColor">
      <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM8 4.1c1.32 0 2.35.88 2.35 2.1 0 .8-.38 1.28-1.1 1.79-.55.39-.7.6-.7 1.04v.22a.55.55 0 0 1-1.1 0v-.35c0-.76.3-1.2 1-1.7.53-.38.7-.6.7-1 0-.55-.47-.95-1.15-.95-.7 0-1.18.42-1.2 1.03a.55.55 0 0 1-1.1-.03C5.62 4.99 6.64 4.1 8 4.1Zm0 6.6a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5Z" />
    </svg>
  );
}

/** A clickable evidence bullet that highlights its source span on click. */
export function EvidenceBullet({
  valence,
  statement,
  span,
  isActive,
  onSelect,
}: {
  valence: Valence;
  statement: string;
  span: SourceSpan | null;
  isActive: boolean;
  onSelect: () => void;
}) {
  const clickable = Boolean(span?.start != null);
  return (
    <li>
      <button
        type="button"
        onClick={clickable ? onSelect : undefined}
        aria-disabled={!clickable}
        className={`group flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left text-[13px] leading-relaxed transition ${
          isActive
            ? "border-accent-500/70 bg-accent-500/10"
            : "border-transparent bg-ink-850/60 hover:border-ink-600"
        } ${clickable ? "cursor-pointer" : "cursor-default"}`}
      >
        <span className="mt-0.5 shrink-0">
          <ValenceIcon valence={valence} />
        </span>
        <span className="flex-1">
          <span className="sr-only">{VALENCE_LABEL[valence]}: </span>
          <span className="text-slate-soft">{statement}</span>
          {clickable ? (
            <span className="mt-1 block truncate font-mono text-[11px] text-accent-400/70 group-hover:text-accent-400">
              “{span!.text}”
            </span>
          ) : (
            <span className="mt-1 block text-[11px] italic text-slate-muted">
              no source span — describes absent information
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

/* ---------------------------------------------------------------------------
   Answer + label rendering
   --------------------------------------------------------------------------- */

export function AnswerChip({ answer }: { answer: Answer }) {
  const map = {
    YES: { tone: "support" as const, glyph: "✓" },
    NO: { tone: "against" as const, glyph: "✕" },
    UNKNOWN: { tone: "unknown" as const, glyph: "?" },
  };
  const { tone, glyph } = map[answer];
  return (
    <Pill tone={tone} className="font-mono">
      <span aria-hidden>{glyph}</span>
      {answer}
    </Pill>
  );
}

export const SUPPORT_TONE: Record<SupportLabel, "support" | "accent" | "unknown" | "neutral"> = {
  "Strong support": "support",
  "Moderate support": "accent",
  "Limited support": "unknown",
  "Insufficient evidence": "neutral",
};

/** Four filled segments for the four qualitative strength levels. */
export function SupportMeter({ label }: { label: SupportLabel }) {
  const filled = {
    "Strong support": 4,
    "Moderate support": 3,
    "Limited support": 2,
    "Insufficient evidence": 1,
  }[label];
  const color = {
    "Strong support": "bg-support-400",
    "Moderate support": "bg-accent-400",
    "Limited support": "bg-unknown-400",
    "Insufficient evidence": "bg-slate-muted",
  }[label];
  return (
    <span className="inline-flex items-center gap-2" title={label}>
      <span className="flex gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={`h-1.5 w-4 rounded-full ${i < filled ? color : "bg-ink-700"}`} />
        ))}
      </span>
      <span className="text-[11px] font-medium text-slate-soft">{label}</span>
    </span>
  );
}

export function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <p className={`text-[11px] leading-relaxed text-slate-muted ${className}`}>
      Research prototype for structured causality assessment. It does not establish medical
      causation, is <strong className="font-semibold text-slate-soft">not a medical device</strong>,
      and is not a clinical decision tool. Synthetic example narratives contain no
      patient-identifiable information.
    </p>
  );
}
