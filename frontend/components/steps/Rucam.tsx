"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { RucamCategory } from "@/lib/api";
import { Button, Callout, Field, Panel, Pill, inputClass } from "../ui";
import { SourceQuote, StatusChip } from "../review";
import type { StepProps } from "./types";

const PATTERN_LABEL: Record<string, string> = {
  HEPATOCELLULAR: "Hepatocellular (R > 5)",
  CHOLESTATIC: "Cholestatic (R < 2)",
  MIXED: "Mixed (R 2–5)",
  UNKNOWN: "Not yet determined",
};

const BANDS = [
  { name: "Excluded", from: -9, to: 0 },
  { name: "Unlikely", from: 1, to: 2 },
  { name: "Possible", from: 3, to: 5 },
  { name: "Probable", from: 6, to: 8 },
  { name: "Highly probable", from: 9, to: 14 },
];

/** Enter ALT and ALP so the R ratio can fix the injury pattern. */
function LabPanel({
  envelope,
  run,
  busyKey,
}: Pick<StepProps, "envelope" | "run" | "busyKey">) {
  const rucam = envelope.case.rucam;
  const [alt, setAlt] = useState("");
  const [altUln, setAltUln] = useState("");
  const [alp, setAlp] = useState("");
  const [alpUln, setAlpUln] = useState("");

  useEffect(() => {
    if (!rucam) return;
    setAlt(rucam.labs.alt?.toString() ?? "");
    setAltUln(rucam.labs.alt_uln?.toString() ?? "");
    setAlp(rucam.labs.alp?.toString() ?? "");
    setAlpUln(rucam.labs.alp_uln?.toString() ?? "");
  }, [rucam?.labs.alt, rucam?.labs.alt_uln, rucam?.labs.alp, rucam?.labs.alp_uln, rucam]);

  if (!rucam) return null;

  return (
    <Panel
      title="Injury pattern"
      subtitle="R = (ALT ÷ ALT upper limit) ÷ (ALP ÷ ALP upper limit). The pattern changes how the first three categories score, so RUCAM cannot be applied without it."
      aside={
        rucam.r_ratio != null ? (
          <div className="text-right">
            <p className="font-mono text-lg font-semibold leading-none text-accent-400">
              R = {rucam.r_ratio}
            </p>
            <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-soft">
              {PATTERN_LABEL[rucam.pattern]}
            </p>
          </div>
        ) : (
          <Pill tone="unknown">pattern undetermined</Pill>
        )
      }
    >
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="ALT">
          <input value={alt} onChange={(e) => setAlt(e.target.value)} className={inputClass} inputMode="decimal" />
        </Field>
        <Field label="ALT upper limit">
          <input value={altUln} onChange={(e) => setAltUln(e.target.value)} className={inputClass} inputMode="decimal" />
        </Field>
        <Field label="Alk phos">
          <input value={alp} onChange={(e) => setAlp(e.target.value)} className={inputClass} inputMode="decimal" />
        </Field>
        <Field label="Alk phos upper limit">
          <input value={alpUln} onChange={(e) => setAlpUln(e.target.value)} className={inputClass} inputMode="decimal" />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          tone="primary"
          busy={busyKey === "rucam-labs"}
          onClick={() =>
            run("rucam-labs", () =>
              api.setRucamLabs(envelope.case.id, {
                alt: alt ? Number(alt) : null,
                alt_uln: altUln ? Number(altUln) : null,
                alp: alp ? Number(alp) : null,
                alp_uln: alpUln ? Number(alpUln) : null,
              }),
            )
          }
        >
          Set values
        </Button>
        <p className="text-[11px] text-slate-muted">
          Use the first values that qualified as indicating liver injury, per the manual.
        </p>
      </div>
    </Panel>
  );
}

export default function Rucam({ envelope, run, suggest, busyKey, active, onSelectSpan }: StepProps) {
  const { case: doc } = envelope;
  const rucam = doc.rucam;
  const [categories, setCategories] = useState<RucamCategory[]>([]);

  useEffect(() => {
    api.getRucamCategories().then(setCategories).catch(() => undefined);
  }, []);

  if (!rucam) return null;

  if (!rucam.applicable) {
    return (
      <Panel title="RUCAM" subtitle="Roussel Uclaf Causality Assessment Method">
        <Callout tone="neutral" title="Not applicable to this case">
          {rucam.not_applicable_reason}
        </Callout>
      </Panel>
    );
  }

  const answered = rucam.answers.filter(
    (a) => a.reviewer_answer && a.reviewer_status.startsWith("REVIEWER"),
  ).length;

  return (
    <div className="space-y-5">
      <Panel
        title="RUCAM framework result"
        subtitle="The liver-specific instrument. Totalled in application code from your answers only, exactly as for Naranjo."
        aside={
          <div className="flex items-center gap-3">
            <div className="text-right">
              {rucam.calculable ? (
                <>
                  <p className="font-mono text-2xl font-semibold leading-none text-accent-400">
                    {rucam.total != null && rucam.total > 0 ? `+${rucam.total}` : rucam.total}
                  </p>
                  <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-soft">
                    {rucam.classification}
                  </p>
                </>
              ) : (
                <Pill tone="unknown">not calculable</Pill>
              )}
            </div>
            <Button size="sm" busy={busyKey === "suggest-rucam"} onClick={() => suggest("rucam")}>
              Suggest answers
            </Button>
          </div>
        }
        className="border-amber-400/25"
      >
        {!rucam.calculable && rucam.blocking_reasons.length > 0 && (
          <div className="space-y-2.5">
            {rucam.blocking_reasons.map((reason, i) => (
              <Callout key={i} tone="unknown" title="RUCAM must not be scored">
                {reason}
              </Callout>
            ))}
            <p className="text-[11px] leading-relaxed text-slate-muted">
              Refusing to produce a number here is the manual&rsquo;s own rule, not a limitation
              of this tool. A RUCAM score in these circumstances would be misleading.
            </p>
          </div>
        )}

        {rucam.calculable && (
          <>
            <div className="flex text-[10px] text-slate-muted">
              {BANDS.map((b) => (
                <span
                  key={b.name}
                  style={{ width: `${((b.to - b.from + 1) / 24) * 100}%` }}
                  className={`border-r border-ink-800 px-1 text-center last:border-r-0 ${
                    rucam.classification === b.name ? "font-semibold text-accent-400" : ""
                  }`}
                >
                  {b.name}
                </span>
              ))}
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-muted">
              Range −9 to +14. Excluded ≤0, unlikely 1–2, possible 3–5, probable 6–8, highly
              probable &gt;8. This is a <strong className="text-slate-soft">framework result</strong>,
              not your conclusion.
            </p>
          </>
        )}

        <p className="mt-3 text-[10.5px] leading-relaxed text-slate-muted">
          Weights transcribed from the {" "}
          <a
            href="https://www.ncbi.nlm.nih.gov/books/NBK548272/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-400 underline underline-offset-2"
          >
            RUCAM Manual of Operations
          </a>{" "}
          in LiverTox. {answered} of {rucam.answers.length} categories answered.
        </p>
      </Panel>

      <LabPanel envelope={envelope} run={run} busyKey={busyKey} />

      {categories.map((category) => {
        const answer = rucam.answers.find((a) => a.category === category.key);
        if (!answer) return null;
        const key = `rucam-${category.key}`;
        const isActive = active?.sourceId === key;
        const disagrees =
          answer.ai_answer &&
          answer.reviewer_status.startsWith("REVIEWER") &&
          answer.reviewer_answer !== answer.ai_answer;

        return (
          <Panel
            key={category.key}
            title={`${category.number}. ${category.title}`}
            subtitle={category.question}
            aside={
              <div className="flex items-center gap-2">
                <StatusChip status={answer.reviewer_status} />
                <span
                  className={`font-mono text-[13px] ${
                    answer.score > 0
                      ? "text-support-400"
                      : answer.score < 0
                        ? "text-against-400"
                        : "text-slate-muted"
                  }`}
                >
                  {answer.score > 0 ? `+${answer.score}` : answer.score}
                </span>
              </div>
            }
          >
            {category.note && (
              <p className="mb-3 text-[11.5px] leading-relaxed text-slate-muted">{category.note}</p>
            )}

            {answer.ai && (
              <p className="mb-2 text-[11.5px] text-violet-300">
                AI suggests: {category.options.find((o) => o.key === answer.ai_answer)?.label ?? answer.ai_answer}
                {answer.ai.rationale ? ` — ${answer.ai.rationale}` : ""}
              </p>
            )}
            {answer.ai && (
              <SourceQuote
                item={{
                  ai: answer.ai,
                  reviewer_status: answer.reviewer_status,
                  reviewer_value: null,
                  reviewer_note: answer.reviewer_note,
                  origin: "AI",
                  reviewed_at: answer.reviewed_at,
                }}
                isActive={isActive}
                onSelect={() => {
                  const span = answer.ai?.span;
                  if (!span || span.start == null) return;
                  onSelectSpan(isActive ? null : { span, sourceId: key, label: category.title });
                }}
              />
            )}

            <ul className="mt-2.5 space-y-1.5">
              {category.options.map((option) => {
                const chosen =
                  answer.reviewer_answer === option.key && answer.reviewer_status.startsWith("REVIEWER");
                const points =
                  option.points[rucam.pattern] ?? option.points["*"] ?? 0;
                return (
                  <li key={option.key}>
                    <button
                      type="button"
                      disabled={busyKey === key}
                      onClick={() =>
                        run(key, () =>
                          api.reviewEntity(doc.id, "rucam", category.key, { value: option.key }),
                        )
                      }
                      className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition disabled:opacity-40 ${
                        chosen
                          ? "border-accent-500/60 bg-accent-500/10"
                          : "border-ink-700/60 bg-ink-850/40 hover:border-ink-600"
                      }`}
                    >
                      <span
                        className={`grid h-4 w-4 shrink-0 place-items-center rounded-full border text-[9px] ${
                          chosen ? "border-accent-400 bg-accent-400 text-ink-950" : "border-ink-600"
                        }`}
                        aria-hidden
                      >
                        {chosen ? "•" : ""}
                      </span>
                      <span className="flex-1 text-[12.5px] leading-snug text-slate-soft">
                        {option.label}
                      </span>
                      {option.blocks_scoring ? (
                        <Pill tone="unknown">stops scoring</Pill>
                      ) : (
                        <span className="shrink-0 font-mono text-[11px] text-slate-muted">
                          {points > 0 ? `+${points}` : points}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>

            {disagrees && (
              <div className="mt-2">
                <Pill tone="accent">overrides AI</Pill>
              </div>
            )}
          </Panel>
        );
      })}
    </div>
  );
}
