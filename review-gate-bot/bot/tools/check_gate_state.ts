import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readGateState } from "../lib/gh.js";
import { readGateFixture } from "../lib/fixtures.js";

const Sha = z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA");

/**
 * The gate state at one head, and the one step it allows next.
 *
 * The order itself lives in `bot/lib/gate.ts` and is unit-tested without a
 * model. This tool only gathers the inputs: reviewer verdicts pinned to the
 * SHA, and the recorded suite result. An eval session reads those from the
 * case's `gate.json` instead of GitHub.
 */
export default defineTool({
  description:
    "Gate state at one head SHA: each reviewer's formal verdict pinned to that exact SHA, the suite result, and the single next step the gate allows. Do not decide the order yourself.",
  inputSchema: z.object({ headSha: Sha }),
  effect: "read",
  async execute({ headSha }, ctx) {
    if (ctx.session.purpose === "eval") {
      const fixture = await readGateFixture(ctx.workspaceDir);
      if (fixture === undefined) {
        throw new Error("eval session without a seeded gate.json");
      }
      return { ...fixture, headSha, source: "fixture" };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("check_gate_state needs a GitHub pull request session");
    }
    const octokit = await ctx.host.github.getOctokit();
    const state = await readGateState({ octokit, kv: ctx.host.kv, ref, headSha });
    return {
      headSha: state.headSha,
      mc: state.mc,
      cursor: state.cursor,
      ditto: state.ditto,
      replit: state.replit,
      suite: state.suite,
      replitTagged: state.replitTagged,
      next: state.next,
      source: "github",
    };
  },
});
