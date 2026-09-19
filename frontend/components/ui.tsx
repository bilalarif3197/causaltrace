import type { ReactNode } from "react";

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
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-700/60 px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-slate-soft">
              {title}
            </h2>
            {subtitle && <div className="mt-1 text-xs leading-relaxed text-slate-muted">{subtitle}</div>}
          </div>
          {aside}
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
