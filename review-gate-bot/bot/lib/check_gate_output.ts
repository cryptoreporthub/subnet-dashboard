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

export function buildCheckGateStateOutput(
  pr: PrSnapshot,
  gate: GateState,
  source: CheckGateStateOutput["source"],
): CheckGateStateOutput {
  const out: CheckGateStateOutput = {
    number: pr.number,
    headSha: pr.headSha,
    baseSha: pr.baseSha,
    draft: pr.draft,
    title: pr.title,
    files: pr.files,
    url: pr.url,
    fileCount: pr.files.length,
    mc: gate.mc,
    cursor: gate.cursor,
    ditto: gate.ditto,
    replit: gate.replit,
    suite: gate.suite,
    replitTagged: gate.replitTagged,
    next: gate.next,
    source,
  };
  if (gate.suiteDetail !== undefined) {
    out.suiteDetail = gate.suiteDetail;
  }
  return out;
}
