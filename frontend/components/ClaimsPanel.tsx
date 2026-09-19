"use client";

import { useState } from "react";
import type { ActiveSpan, AnalysisResult, Claim } from "@/lib/types";
import { Panel, Pill } from "./ui";

const SLOT_LABEL: Record<string, string> = {
  suspected_drug: "Suspected drug",
  concomitant_drugs: "Concomitant drugs",
  drug_timing: "Drug timing",
  doses: "Doses",
  adverse_event: "Adverse event",
  event_onset: "Event onset",
  diagnoses_comorbidities: "Diagnoses",
  infections: "Infections",
  labs: "Labs",
  diagnostic_tests: "Diagnostic tests",
  treatment_withdrawal: "Withdrawal",
  dechallenge_outcome: "Dechallenge",
  rechallenge: "Rechallenge",
  previous_exposure: "Previous exposure",
  dose_response: "Dose-response",
  drug_levels: "Drug levels",
  alternative_causes: "Alternative causes",
  objective_evidence: "Objective evidence",
  prior_knowledge: "Prior knowledge",
};

function ClaimRow({
  claim,
  active,
  onSelect,
}: {
  claim: Claim;
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  const clickable = claim.span?.start != null && !claim.dropped;
  const isActive = active?.sourceId === claim.id;

  return (
    <li
      className={`rounded-lg border px-3.5 py-2.5 transition ${
        claim.dropped
          ? "border-against-400/30 bg-against-bg/40"
          : isActive
            ? "border-accent-500/70 bg-accent-500/10"
            : "border-ink-700/60 bg-ink-850/40"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-muted">
          {SLOT_LABEL[claim.slot] ?? claim.slot}
        </span>
        {claim.dropped ? (
          <Pill tone="against">rejected</Pill>
        ) : claim.status === "UNKNOWN" ? (
          <Pill tone="unknown">not reported</Pill>
        ) : (
          <Pill tone="support">grounded</Pill>
        )}
        {!claim.dropped && claim.status === "SUPPORTED" && (
          <span className="font-mono text-[10px] text-slate-muted">
            conf {claim.confidence.toFixed(2)}
          </span>
        )}
      </div>

      <p
        className={`mt-1.5 text-[12.5px] leading-snug ${
          claim.dropped ? "text-slate-muted line-through" : "text-slate-soft"
        }`}
      >
        {claim.claim}
      </p>

      {claim.dropped && claim.drop_reason && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-against-400">
          Verifier: {claim.drop_reason}
        </p>
      )}

      {clickable && (
        <button
          type="button"
          onClick={() =>
            onSelect(
              isActive ? null : { span: claim.span!, sourceId: claim.id, label: claim.claim },
            )
          }
          className="mt-1.5 block max-w-full truncate text-left font-mono text-[11px] text-accent-400/75 underline decoration-dotted underline-offset-2 transition hover:text-accent-400"
        >
          “{claim.span!.text}”
        </button>
      )}
    </li>
  );
}

export default function ClaimsPanel({
  result,
  active,
  onSelect,
}: {
  result: AnalysisResult;
  active: ActiveSpan | null;
  onSelect: (a: ActiveSpan | null) => void;
}) {
  const [showUnknown, setShowUnknown] = useState(false);

  const grounded = result.claims.filter((c) => c.status === "SUPPORTED" && !c.dropped);
  const rejected = result.claims.filter((c) => c.dropped);
  const unknown = result.claims.filter((c) => c.status === "UNKNOWN" && !c.dropped);

  return (
    <Panel
      title="Extracted evidence"
      subtitle="Stage 1 extraction, audited by an independent Stage 4 verification pass."
      aside={
        <div className="shrink-0 text-right">
          <p className="font-mono text-[13px] text-slate-soft">
            {(result.unsupported_assertion_rate * 100).toFixed(1)}%
          </p>
          <p className="text-[10px] uppercase tracking-wider text-slate-muted">unsupported rate</p>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <Pill tone="support">{grounded.length} grounded</Pill>
        <Pill tone="unknown">{unknown.length} not reported</Pill>
        <Pill tone={rejected.length ? "against" : "neutral"}>{rejected.length} rejected</Pill>
      </div>

      {rejected.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-against-400">
            Rejected by verification
          </h3>
          <p className="mb-2 text-[11px] leading-relaxed text-slate-muted">
            These were proposed during extraction and then removed because the cited text did not
            actually support them. They are kept visible rather than silently deleted.
          </p>
          <ul className="space-y-1.5">
            {rejected.map((c) => (
              <ClaimRow key={c.id} claim={c} active={active} onSelect={onSelect} />
            ))}
          </ul>
        </div>
      )}

      <ul className="space-y-1.5">
        {grounded.map((c) => (
          <ClaimRow key={c.id} claim={c} active={active} onSelect={onSelect} />
        ))}
      </ul>

      {unknown.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setShowUnknown((v) => !v)}
            className="text-[11px] text-slate-muted underline decoration-dotted underline-offset-2 transition hover:text-accent-400"
          >
            {showUnknown ? "Hide" : "Show"} {unknown.length} slots the narrative never reported
          </button>
          {showUnknown && (
            <ul className="mt-2 space-y-1.5">
              {unknown.map((c) => (
                <ClaimRow key={c.id} claim={c} active={active} onSelect={onSelect} />
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
