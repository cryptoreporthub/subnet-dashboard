import { defineEval, type EvalTestContext } from "@grok/agent-sdk/evals";
import { loadJson } from "@grok/agent-sdk/evals/loaders";
import type { GateState } from "../bot/lib/gate.js";
import { sendWithRetry } from "./eval-turn.js";
import { R1PACKB_FIXTURES } from "./r1packb-cases.js";

/** R1-A: run-only eval (Claude scores). No deterministic grading or judge. */

type PrFixture = { number: number; headSha: string; title: string };

const ITERATIONS = 3;
const TURN_TIMEOUT_MS = 600_000;

async function seeded(fixture: string) {
  const p = await loadJson<PrFixture>(`evals/fixtures/${fixture}/pr.json`);
  const g = await loadJson<GateState & { note?: string; prBody?: string }>(`evals/fixtures/${fixture}/gate.json`);
  const diff = await loadJson(`evals/fixtures/${fixture}/diff.json`);
  const repo = await loadJson<{ files: Record<string, string> }>(`evals/fixtures/${fixture}/repo.json`);
  const body = g.prBody ? `\n${g.prBody}` : "";
  return {
    p,
    prompt: [`Review PR ${p.number} (${p.title}) at head ${p.headSha}.`, body, "", "Post your verdict with post_verdict."].join("\n"),
    files: {
      "pr.json": JSON.stringify(p, null, 2),
      "gate.json": JSON.stringify(g, null, 2),
      "diff.json": JSON.stringify(diff),
      "repo.json": JSON.stringify(repo),
    },
  };
}

export default defineEval({
  tags: ["r1packb", "gate"],
  cases: R1PACKB_FIXTURES.flatMap((fixture) => {
    const slug = fixture.replace(/^r1b-/, "");
    return {
      id: slug,
      description: `R1-A pack B: ${fixture}`,
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
