import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineEval, type EvalTestContext } from "@grok/agent-sdk/evals";
import { loadJson } from "@grok/agent-sdk/evals/loaders";
import type { GateState } from "../bot/lib/gate.js";
import { sendWithRetry } from "./eval-turn.js";
import { TURN_TIMEOUT_MS } from "./hard-specs.js";
import { promptForSlug } from "./r24-prompts.js";

/**
 * r24 Stage A: one eval case per slug in `exam-artifacts/r24/stage-a-manifest.json`.
 * Same turn shape as r23 hard/regression runs (pinned workspace, review prompt, post_verdict).
 * No deterministic det gates — grading is `score-r24-first-line.py` on the posted verdict only.
 */

type StageRow = { slug: string; fixture: string; oracle: string };
type StageManifest = { stageA: StageRow[] };

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const STAGE_MANIFEST: StageManifest = JSON.parse(
  readFileSync(join(REPO_ROOT, "exam-artifacts/r24/stage-a-manifest.json"), "utf8"),
);

type PrFixture = { number: number; headSha: string };

async function seeded(fixture: string): Promise<{ p: PrFixture; files: Record<string, string> }> {
  const p = await loadJson<PrFixture>(`evals/fixtures/${fixture}/pr.json`);
  const g = await loadJson<GateState & { note?: string }>(`evals/fixtures/${fixture}/gate.json`);
  const diff = await loadJson(`evals/fixtures/${fixture}/diff.json`);
  const repo = await loadJson(`evals/fixtures/${fixture}/repo.json`);
  return {
    p,
    files: {
      "pr.json": JSON.stringify(p, null, 2),
      "gate.json": JSON.stringify(g, null, 2),
      "diff.json": JSON.stringify(diff),
      "repo.json": JSON.stringify(repo),
    },
  };
}

async function runCase(t: EvalTestContext, slug: string, fixture: string): Promise<void> {
  const { p, files } = await seeded(fixture);
  await sendWithRetry(t, promptForSlug(slug, p.number, p.headSha), { workspaceFiles: files });
  t.succeeded();
}

export default defineEval({
  tags: ["r24", "gate", "stage-a"],
  cases: STAGE_MANIFEST.stageA.map((row) => ({
    id: row.slug,
    description: `r24 Stage A ${row.fixture} (oracle ${row.oracle})`,
    iterations: 1,
    timeoutMs: TURN_TIMEOUT_MS,
    test: (t) => runCase(t, row.slug, row.fixture),
  })),
});
