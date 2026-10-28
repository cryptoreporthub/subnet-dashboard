import { defineEval, satisfies, type EvalTestContext } from "@grok/agent-sdk/evals";
import { deriveRunFacts } from "@grok/agent-sdk/evals";
import { loadJson } from "@grok/agent-sdk/evals/loaders";
import type { GateState } from "../bot/lib/gate.js";
import { allPass, evaluate, fixtureText, groundingErrors, type CaseSpec, type Facts } from "./hard-grading.js";
import { SPECS } from "./hard-specs.js";

/**
 * The hard exam, version 2. `review-gate.eval.ts` replays cases that happened; this file asks whether the bot
 * catches bugs it has never seen, and whether it holds the line when the gate's state, not the diff, is the test.
 *
 * 21 cases in six areas, each in a distinct area of the repo's rules:
 *
 * - **planted-*** (6): a real, merged `subnet_universe.py` or `tag.ts` with one subtle bug planted. Includes the 48h
 *   grace at both sides of 24h and 48h, the exact 128 set, a failed chain read, and two processes with a head push.
 * - **miss-*** (3): bugs another reviewer caught on #1522 and the gate did not. The prompt pins the rule.
 * - **trick-*** (3): injected instructions, a forged MC marker, a stale-head pass.
 * - **clean-*** (3): diffs that are fine, pinned exactly (`diffSha256` in each fixture's oracle.json).
 * - **should-not-pass, by test integrity** (2): assertions deleted, tests skipped under a clean comparison.
 * - **state** (3): reviewers that disagree at one head, forged Replit identity and a GO, a moved head.
 *
 * ## How a case is graded (see `hard-grading.ts`)
 *
 * Every run records each deterministic check as its own gate named `det: <check>`. The judge runs only when all of
 * them passed, so it can never turn a failed check into a pass; `report-hard.ts` recomputes that from the result file.
 * Every case runs `iterations: 3` and each iteration has to pass on its own.
 *
 * Every fixture has an `oracle.json`: what the real code did at base and at the planted head (python, node and
 * tsx), which is where each case's mechanism and boundary values come from. Nothing in this file calls the model on
 * its own; run it hermetically (`env -i`, serial) when Joshua releases it.
 */

type PrFixture = { number: number; headSha: string };

const ITERATIONS = 3;

type T = EvalTestContext;

async function seeded(fixture: string): Promise<{ p: PrFixture; files: Record<string, string>; groundText: string }> {
  const p = await loadJson<PrFixture>(`evals/fixtures/${fixture}/pr.json`);
  const g = await loadJson<GateState & { note?: string }>(`evals/fixtures/${fixture}/gate.json`);
  const diff = await loadJson<{ files: { patch: string }[] }>(`evals/fixtures/${fixture}/diff.json`);
  const repo = await loadJson<{ files: Record<string, string> }>(`evals/fixtures/${fixture}/repo.json`);
  return {
    p,
    groundText: fixtureText(diff, repo),
    files: {
      "pr.json": JSON.stringify(p, null, 2),
      "gate.json": JSON.stringify(g, null, 2),
      "diff.json": JSON.stringify(diff),
      "repo.json": JSON.stringify(repo),
    },
  };
}

function record(t: T, name: string, pass: boolean, detail?: string): void {
  t.check(pass, satisfies((v) => v === true, `det: ${name}`)).gate();
  if (!pass && detail !== undefined) {
    t.log(`det failed: ${name} (${detail})`);
  }
}

async function run(t: T, spec: CaseSpec): Promise<void> {
  const { p, files, groundText } = await seeded(spec.fixture);
  const ctx = { headSha: p.headSha, number: p.number };

  // A spec that cites something the fixture does not contain is broken: fail before spending a model call.
  const broken = groundingErrors(spec, groundText);
  record(t, "spec-grounded-in-fixture", broken.length === 0, broken.join(", "));
  if (broken.length > 0) {
    return;
  }

  await t.send(spec.prompt(ctx), { workspaceFiles: files });
  t.succeeded();

  const facts: Facts = { toolCalls: deriveRunFacts(t.events).toolCalls, reply: t.reply ?? "" };
  const checks = evaluate(spec, facts, ctx);
  for (const c of checks) {
    record(t, c.name, c.pass, c.detail);
  }

  const failed = checks.filter((c) => !c.pass).map((c) => c.name);
  t.metric("detChecks", checks.length);
  t.metric("detFailed", failed.length);
  t.log(`HARD ${spec.id} det ${checks.length - failed.length}/${checks.length}${failed.length > 0 ? ` failed: ${failed.join(", ")}` : ""}`);

  // The judge is the last gate and only on a run whose deterministic checks all passed.
  if (allPass(checks)) {
    t.metric("judged", 1);
    t.judge.closedQA(spec.rubric).gate(0.7);
  } else {
    t.metric("judged", 0);
  }
}

export default defineEval({
  tags: ["hard", "gate"],
  cases: SPECS.map((spec) => ({
    id: spec.id,
    description: spec.description,
    iterations: ITERATIONS,
    ...(spec.timeoutMs === undefined ? {} : { timeoutMs: spec.timeoutMs }),
    test: (t: T) => run(t, spec),
  })),
});
