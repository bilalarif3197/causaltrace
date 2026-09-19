import type { ReactNode } from "react";

/* --------------------------------------------------------------------------
   Icons

   Drawn rather than typed. Dingbat characters render inconsistently across
   platforms and some fonts substitute colour emoji for them, which is not what
   a clinical review tool should look like. These also inherit currentColor, so
   they carry the same semantic colour as their label.
   -------------------------------------------------------------------------- */

type IconProps = { className?: string };
const base = (c?: string) => `inline-block shrink-0 ${c ?? "h-3.5 w-3.5"}`;

export function CheckIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5 6.2 11.7 13 4.9" />
    </svg>
  );
}

export function PencilIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11.2 2.6a1.6 1.6 0 0 1 2.3 2.3L5.6 12.8l-3 .7.7-3z" />
    </svg>
  );
}

export function CrossIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

export function WarnIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="currentColor">
      <path d="M7.13 1.94a1 1 0 0 1 1.74 0l6 10.56A1 1 0 0 1 14 14H2a1 1 0 0 1-.87-1.5zM8 5.25a.8.8 0 0 0-.8.86l.22 2.94a.58.58 0 0 0 1.16 0l.22-2.94A.8.8 0 0 0 8 5.25m0 5.1a.85.85 0 1 0 0 1.7.85.85 0 0 0 0-1.7" />
    </svg>
  );
}

export function QuestionIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="currentColor">
      <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13m0 2.6c1.32 0 2.35.88 2.35 2.1 0 .8-.38 1.28-1.1 1.79-.55.39-.7.6-.7 1.04v.22a.55.55 0 0 1-1.1 0v-.35c0-.76.3-1.2 1-1.7.53-.38.7-.6.7-1 0-.55-.47-.95-1.15-.95-.7 0-1.18.42-1.2 1.03a.55.55 0 0 1-1.1-.03C5.62 4.99 6.64 4.1 8 4.1m0 6.6a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5" />
    </svg>
  );
}

/** Marks machine-generated content. A four-point star, not an emoji. */
export function AiIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="currentColor">
      <path d="M8 1.2 9.5 5.8a1 1 0 0 0 .7.7l4.6 1.5-4.6 1.5a1 1 0 0 0-.7.7L8 14.8l-1.5-4.6a1 1 0 0 0-.7-.7L1.2 8l4.6-1.5a1 1 0 0 0 .7-.7z" />
    </svg>
  );
}

export function DotIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={base(className)} fill="currentColor">
      <circle cx="8" cy="8" r="3.2" />
    </svg>
  );
}

export function Panel({
  title,
  subtitle,
  aside,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`rounded-xl border border-ink-700/70 bg-ink-900/60 ${className}`}>
      {title && (
        <header className="flex flex-wrap items-start gap-x-4 gap-y-3 border-b border-ink-700/60 px-5 py-3.5">
          {/* min-w-[16rem] keeps a long subtitle from squeezing the aside to
              nothing, and ml-auto keeps the aside right-aligned even after it
              wraps onto its own line. */}
          <div className="min-w-[16rem] flex-1">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-slate-soft">
              {title}
            </h2>
            {subtitle && <div className="mt-1 text-xs leading-relaxed text-slate-muted">{subtitle}</div>}
          </div>
          {aside && <div className="ml-auto flex shrink-0 items-start gap-2">{aside}</div>}
        </header>
      )}
      <div className={bodyClassName || "p-5"}>{children}</div>
    </section>
  );
}

export type Tone = "neutral" | "accent" | "support" | "against" | "unknown" | "ai";

const TONES: Record<Tone, string> = {
  neutral: "border-ink-600 bg-ink-800/80 text-slate-soft",
  accent: "border-accent-600/60 bg-accent-500/10 text-accent-400",
  support: "border-support-400/40 bg-support-bg text-support-400",
  against: "border-against-400/40 bg-against-bg text-against-400",
  unknown: "border-unknown-400/40 bg-unknown-bg text-unknown-400",
  ai: "border-violet-400/40 bg-violet-400/10 text-violet-300",
};

export function Pill({
  children,
  tone = "neutral",
  className = "",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  tone = "ghost",
  disabled,
  busy,
  size = "md",
  className = "",
  title,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: "primary" | "ghost" | "danger" | "success";
  disabled?: boolean;
  busy?: boolean;
  size?: "sm" | "md";
  className?: string;
  title?: string;
  type?: "button" | "submit";
}) {
  const tones = {
    primary: "bg-accent-500 text-ink-950 hover:bg-accent-400 disabled:bg-ink-700 disabled:text-slate-muted",
    ghost: "border border-ink-600 text-slate-soft hover:border-accent-600/60 hover:text-accent-400 disabled:opacity-40",
    danger: "border border-against-400/40 text-against-400 hover:bg-against-bg disabled:opacity-40",
    success: "border border-support-400/40 text-support-400 hover:bg-support-bg disabled:opacity-40",
  } as const;
  const sizes = { sm: "px-2.5 py-1 text-[11px]", md: "px-4 py-2 text-[13px]" } as const;
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed ${tones[tone]} ${sizes[size]} ${className}`}
    >
      {busy && (
        <span
          className="h-3 w-3 animate-spin rounded-full border-2 border-current/30 border-t-current"
          aria-hidden
        />
      )}
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-muted">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-slate-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-lg border border-ink-700 bg-ink-950/70 px-3 py-2 text-[13px] text-slate-soft placeholder:text-ink-500 focus:border-accent-600 focus:outline-none focus:ring-1 focus:ring-accent-600/40";

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-ink-700 px-5 py-8 text-center">
      <p className="text-[13px] leading-relaxed text-slate-muted">{children}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Callout({
  tone = "unknown",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  const border = {
    neutral: "border-ink-600 bg-ink-850/60",
    accent: "border-accent-600/40 bg-accent-500/10",
    support: "border-support-400/40 bg-support-bg",
    against: "border-against-400/40 bg-against-bg",
    unknown: "border-unknown-400/40 bg-unknown-bg",
    ai: "border-violet-400/40 bg-violet-400/10",
  }[tone];
  return (
    <div className={`rounded-lg border px-4 py-3 ${border}`}>
      {title && (
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-soft">
          {title}
        </p>
      )}
      <div className="mt-1 text-[12.5px] leading-relaxed text-slate-soft">{children}</div>
    </div>
  );
}

export function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <p className={`text-[11px] leading-relaxed text-slate-muted ${className}`}>
      AI-assisted pharmacovigilance workspace. The AI organises evidence and suggests
      interpretations; the <strong className="font-semibold text-slate-soft">reviewer makes every
      clinically meaningful judgment</strong>. It does not establish medical causation, is not a
      medical device, and is not a clinical decision tool. Demo narratives are synthetic and
      contain no patient-identifiable information.
    </p>
  );
}
