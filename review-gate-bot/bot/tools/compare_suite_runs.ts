import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr, suiteKey } from "../lib/gh.js";
import { readPrFixture } from "../lib/fixtures.js";
import { diffJunit, pytestReachable } from "../lib/suite.js";

const Sha = z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA");

/**
 * Flake-aware base-vs-head comparison of the full pytest suite, from the JUnit
 * XML a cloud runner produced. Records the outcome for this head so
 * `check_gate_state` can read it back in a later process.
 *
 * Carry-over is for a head that changed no pytest-reachable file: the previous
 * head's clean result then still describes this head. A formal review never
 * carries — a new head always needs fresh reviews.
 */
export default defineTool({
  description:
    "Compare full-repo pytest results for base and head from cloud-runner JUnit artifacts. Flake-aware. Records the result for this head. Docs-only carry-over is allowed only when no pytest-reachable file changed.",
  inputSchema: z.object({
    headSha: Sha,
    baseSha: Sha,
    baseJunit: z.string().describe("JUnit XML the runner produced for the base commit."),
    headJunit: z.string().describe("JUnit XML the runner produced for the head commit."),
    knownFlakes: z
      .array(z.string())
      .optional()
      .describe("Known-flaky test ids, `classname::name`. A flip on this list is not a regression."),
    carryFromSha: Sha.optional().describe("A prior head whose suite was clean, to carry from."),
  }),
  effect: "idempotent",
  dryRunResult: () => ({ recorded: false, reason: "dry-run", clean: false }),
  async execute(input, ctx) {
    const isEval = ctx.session.purpose === "eval";
    const fixture = isEval ? await readPrFixture(ctx.workspaceDir) : undefined;

    let changedFiles: string[];
    let currentHeadSha: string;

    if (isEval) {
      if (fixture === undefined) {
        throw new Error("eval session without a seeded pr.json");
      }
      changedFiles = fixture.files;
      currentHeadSha = fixture.headSha;
    } else {
      const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
      if (ref === undefined) {
        throw new Error("compare_suite_runs needs a GitHub pull request session");
      }
      const octokit = await ctx.host.github.getOctokit();
      const pr = await readPr(octokit, ref);
      changedFiles = pr.files;
      currentHeadSha = pr.headSha;
    }

    if (currentHeadSha !== input.headSha) {
      // A comparison for a head that has been replaced would record a result
      // against a SHA nobody is reviewing.
      return { recorded: false, reason: "stale-head", current: currentHeadSha, clean: false };
    }

    if (input.carryFromSha !== undefined) {
      const reachable = pytestReachable(changedFiles);
      if (reachable.length > 0) {
        return {
          recorded: false,
          reason: "pytest-reachable",
          files: reachable,
          carried: false,
          clean: false,
        };
      }
      if (!isEval) {
        const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
        if (ref !== undefined) {
          await ctx.host.kv.put(suiteKey(ref.number, input.headSha), {
            state: "carried",
            carriedFrom: input.carryFromSha,
            at: Date.now(),
          });
        }
      }
      return {
        recorded: true,
        carried: true,
        carryFromSha: input.carryFromSha,
        clean: true,
        newFailures: [],
        fixed: [],
        flakyRetriedOk: [],
        preExisting: [],
      };
    }

    const diff = diffJunit({
      baseXml: input.baseJunit,
      headXml: input.headJunit,
      knownFlakes: input.knownFlakes,
    });

    if (!isEval) {
      const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
      if (ref !== undefined) {
        await ctx.host.kv.put(suiteKey(ref.number, input.headSha), {
          state: diff.clean ? "clean" : "regressed",
          newFailures: diff.newFailures,
          at: Date.now(),
        });
      }
    }

    return { recorded: true, carried: false, ...diff };
  },
});
