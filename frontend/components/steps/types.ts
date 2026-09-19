import type { SuggestStage } from "@/lib/api";
import type { ActiveSpan, CaseEnvelope } from "@/lib/review";

/** Shared contract for every step screen in the workspace. */
export interface StepProps {
  envelope: CaseEnvelope;
  /** Run a mutation and fold the returned envelope back into workspace state. */
  run: (key: string, fn: () => Promise<CaseEnvelope>) => Promise<void>;
  /** Run an AI suggestion stage. Always explicit — never fired automatically. */
  suggest: (stage: SuggestStage) => Promise<void>;
  /** Key of whatever action is currently in flight, or null. */
  busyKey: string | null;
  active: ActiveSpan | null;
  onSelectSpan: (a: ActiveSpan | null) => void;
}
