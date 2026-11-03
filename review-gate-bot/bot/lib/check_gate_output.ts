import type { GateState } from "./gate.js";
import type { PrSnapshot } from "./gh.js";

/** Keys `check_gate_state` may return — production PR fields, gate state, and `fileCount` / `source`. */
export const CHECK_GATE_STATE_OUTPUT_KEYS = [
  "number",
  "headSha",
  "baseSha",
  "draft",
  "title",
  "files",
  "url",
  "fileCount",
  "mc",
  "cursor",
  "ditto",
  "replit",
  "suite",
  "suiteDetail",
  "replitTagged",
  "next",
  "source",
] as const;

export type CheckGateStateOutput = PrSnapshot & GateState & { fileCount: number; source: "fixture" | "github" };

const PR_KEYS: (keyof PrSnapshot)[] = ["number", "headSha", "baseSha", "draft", "title", "files", "url"];
const GATE_KEYS: (keyof GateState)[] = [
  "headSha",
  "mc",
  "cursor",
  "ditto",
  "replit",
  "suite",
  "replitTagged",
  "next",
  "suiteDetail",
];

export function buildCheckGateStateOutput(
  pr: PrSnapshot,
  gate: GateState,
  source: CheckGateStateOutput["source"],
): CheckGateStateOutput {
  const out = {} as CheckGateStateOutput;
  for (const k of PR_KEYS) {
    out[k] = pr[k];
  }
  out.fileCount = pr.files.length;
  for (const k of GATE_KEYS) {
    if (gate[k] !== undefined) {
      (out as GateState)[k] = gate[k];
    }
  }
  out.source = source;
  return out;
}
