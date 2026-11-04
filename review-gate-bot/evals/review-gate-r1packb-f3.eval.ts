import { defineEval, type EvalTestContext } from "@grok/agent-sdk/evals";
import { loadJson } from "@grok/agent-sdk/evals/loaders";
import type { GateState } from "../bot/lib/gate.js";
import { sendWithRetry } from "./eval-turn.js";
import { R1PACKB_F3_FIXTURES } from "./r1packb-f3-cases.js";

/** R1-F3: run-only eval (Claude scores). V1/V2/V3 bars; do not start before R1-A2 publish. */

type PrFixture = { number: number; headSha: string; title: string };

const ITERATIONS = 3;
const TURN_TIMEOUT_MS = 600_000;

async function seeded(fixture: string) {
  const p = await loadJson<PrFixture>(`evals/fixtures/${fixture}/pr.json`);
  const g = await loadJson<GateState>(`evals/fixtures/${fixture}/gate.json`);
  const diff = await loadJson(`evals/fixtures/${fixture}/diff.json`);
  const repo = await loadJson<{ files: Record<string, string> }>(`evals/fixtures/${fixture}/repo.json`);
  return {
    p,
    prompt: [`Review PR ${p.number} (${p.title}) at head ${p.headSha}.`, "", "Post your verdict with post_verdict."].join("\n"),
    files: {
      "pr.json": JSON.stringify(p, null, 2),
      "gate.json": JSON.stringify(g, null, 2),
      "diff.json": JSON.stringify(diff),
      "repo.json": JSON.stringify(repo),
    },
  };
}

export default defineEval({
  tags: ["r1packb", "r1packb-f3", "gate"],
  cases: R1PACKB_F3_FIXTURES.flatMap((fixture) => {
    const slug = fixture.replace(/^r1b-/, "");
    return {
      id: slug,
      description: `R1-F3 pack B: ${fixture}`,
      iterations: ITERATIONS,
      timeoutMs: TURN_TIMEOUT_MS,
      test: async (t: EvalTestContext) => {
        const { prompt, files } = await seeded(fixture);
        await sendWithRetry(t, prompt, { workspaceFiles: files });
        t.succeeded();
      },
    };
  }),
});
