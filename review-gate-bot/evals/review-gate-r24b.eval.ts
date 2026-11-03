import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineEval, type EvalTestContext } from "@grok/agent-sdk/evals";
import type { GateState } from "../bot/lib/gate.js";
import { sendWithRetry } from "./eval-turn.js";
import { TURN_TIMEOUT_MS } from "./hard-specs.js";
import { promptForSlug } from "./r24-prompts.js";

/**
 * r24 Stage B holdout: cases from exam-artifacts/r24/stage-b-manifest.json.
 * Fixtures live under exam-artifacts/r24/fixtures/stage-b/<fixture>/ (not evals/fixtures).
 */

type StageRow = { slug: string; fixture: string; oracle: string };
type StageManifest = { stageB: StageRow[] };

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const STAGE_MANIFEST: StageManifest = JSON.parse(
  readFileSync(join(REPO_ROOT, "exam-artifacts/r24/stage-b-manifest.json"), "utf8"),
);

type PrFixture = { number: number; headSha: string };

function stageBFixtureDir(fixture: string): string {
  return join(REPO_ROOT, "exam-artifacts/r24/fixtures/stage-b", fixture);
}

async function seeded(fixture: string): Promise<{ p: PrFixture; files: Record<string, string> }> {
  const base = stageBFixtureDir(fixture);
  const p = JSON.parse(readFileSync(join(base, "pr.json"), "utf8")) as PrFixture;
  const g = JSON.parse(readFileSync(join(base, "gate.json"), "utf8")) as GateState & { note?: string };
  const diff = JSON.parse(readFileSync(join(base, "diff.json"), "utf8"));
  const repo = JSON.parse(readFileSync(join(base, "repo.json"), "utf8"));
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
  tags: ["r24", "gate", "stage-b"],
  cases: STAGE_MANIFEST.stageB.map((row) => ({
    id: row.slug,
    description: `r24 Stage B ${row.fixture} (oracle ${row.oracle})`,
    iterations: 1,
    timeoutMs: TURN_TIMEOUT_MS,
    test: (t) => runCase(t, row.slug, row.fixture),
  })),
});
