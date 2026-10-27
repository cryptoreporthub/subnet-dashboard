import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { readGateState, readPr } from "../lib/gh.js";
import { readGateFixture, readPrFixture } from "../lib/fixtures.js";

/**
 * This session's pull request and the gate state at its head, in one read.
 *
 * The order itself lives in `bot/lib/gate.ts` and is unit-tested without a
 * model. This tool only gathers the inputs: the PR, reviewer verdicts pinned to
 * its head SHA, and the recorded suite result. The PR comes from the session's
 * continuation key, never from a model-supplied identifier, so the model cannot
 * point a review at another PR. An eval session reads the same fields from the
 * case's `pr.json` and `gate.json` instead of GitHub.
 */
export default defineTool({
  description:
    "Read this session's pull request and the gate at its head: head SHA, base SHA, changed files, draft flag, each reviewer's formal verdict pinned to that exact SHA, the suite result, and the single next step the gate allows. Call this first and review only the head SHA it returns. Do not decide the order yourself.",
  effect: "read",
  async execute(_input, ctx) {
    if (ctx.session.purpose === "eval") {
      const [pr, gate] = await Promise.all([readPrFixture(ctx.workspaceDir), readGateFixture(ctx.workspaceDir)]);
      if (pr === undefined || gate === undefined) {
        throw new Error("eval session without a seeded pr.json and gate.json");
      }
      // The fixture pins its verdicts to one head. Showing them beside another
      // would present gate results as belonging to a head they were never about.
      if (gate.headSha !== pr.headSha) {
        throw new Error(`gate.json is pinned to ${gate.headSha}, not the PR head ${pr.headSha}`);
      }
      return { ...pr, fileCount: pr.files.length, ...gate, source: "fixture" };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("check_gate_state needs a GitHub pull request session");
    }
    const octokit = await ctx.host.github.getOctokit();
    const pr = await readPr(octokit, ref);
    const state = await readGateState({ octokit, kv: ctx.host.kv, ref, headSha: pr.headSha });
    return { ...pr, fileCount: pr.files.length, ...state, source: "github" };
  },
});
