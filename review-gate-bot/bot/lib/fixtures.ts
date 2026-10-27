import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { GateState } from "./gate.js";
import type { PrSnapshot } from "./gh.js";
import type { Diff } from "./repo.js";

/**
 * Eval sessions have no GitHub PR behind them: `continuationKey` is absent, so
 * `parseGitHubPrContinuationKey` returns undefined and a live read would throw.
 *
 * Rather than let every eval degrade into "the tool errored", an eval session
 * reads a pinned snapshot from its own workspace — the two files the eval case
 * seeds with `workspaceFiles`:
 *
 * - `pr.json`   — the PR at the head the case pins
 * - `gate.json` — the gate inputs for that head
 *
 * This is evidence preparation, not judgement: the fixtures are fixed, and the
 * gate logic still runs for real over them.
 */

export const PR_FIXTURE = "pr.json";
export const GATE_FIXTURE = "gate.json";
export const DIFF_FIXTURE = "diff.json";
export const REPO_FIXTURE = "repo.json";

async function readJson<T>(workspaceDir: string, name: string): Promise<T | undefined> {
  try {
    const text = await readFile(join(workspaceDir, name), "utf8");
    return JSON.parse(text) as T;
  } catch {
    return undefined;
  }
}

/** The PR a fixture describes, or undefined when the case did not seed one. */
export function readPrFixture(workspaceDir: string): Promise<PrSnapshot | undefined> {
  return readJson<PrSnapshot>(workspaceDir, PR_FIXTURE);
}

export type GateFixture = {
  headSha: string;
  mc: GateState["mc"];
  cursor: GateState["cursor"];
  ditto: GateState["ditto"];
  replit: GateState["replit"];
  suite: GateState["suite"];
  replitTagged: boolean;
  next: GateState["next"];
};

export function readGateFixture(workspaceDir: string): Promise<GateFixture | undefined> {
  return readJson<GateFixture>(workspaceDir, GATE_FIXTURE);
}

/** The PR's diff as the case pins it, or undefined when the case did not seed one. */
export function readDiffFixture(workspaceDir: string): Promise<Diff | undefined> {
  return readJson<Diff>(workspaceDir, DIFF_FIXTURE);
}

/** File contents at the pinned head: `{ "files": { "<path>": "<text>" } }`. */
export function readRepoFixture(workspaceDir: string): Promise<{ files: Record<string, string> } | undefined> {
  return readJson<{ files: Record<string, string> }>(workspaceDir, REPO_FIXTURE);
}
