import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr, readSuiteRecord, suiteKey, type PrRef } from "../lib/gh.js";
import { readPrFixture } from "../lib/fixtures.js";
import { knownFlakes } from "../lib/flakes.js";
import { fetchJunit, octokitRunner } from "../lib/runner.js";
import { carryDecision, diffJunit } from "../lib/suite.js";

const Sha = z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA");

type Runner = ReturnType<typeof octokitRunner>;

/**
 * The PR a recorded result belongs to. Recording without one would file the
 * result under no PR, so a missing reference is an error, never a default.
 */
function requirePr(ref: PrRef | undefined): PrRef {
  if (ref === undefined) {
    throw new Error("compare_suite_runs needs a GitHub pull request session");
  }
  return ref;
}

/**
 * Flake-aware base-vs-head comparison of the full pytest suite, from the JUnit
 * XML the cloud runner produced **for each SHA**.
 *
 * Nothing here is model-supplied except the two SHAs, and those are checked
 * against the live PR head before anything is recorded:
 *
 * - The XML is fetched from the `pytest-junit` artifact of the `full-suite-junit.yml`
 *   run for that SHA. A missing or expired artifact is a refusal, never an
 *   empty report that parses to "clean".
 * - The flake list is the committed `known-flakes.txt`. It used to be a
 *   tool argument, which let a caller excuse any regression by naming it.
 * - Carry-over needs a **recorded clean** result at the SHA being carried
 *   from, and deny-by-default path rules: only an explicit prose/image
 *   allowlist may carry, so a non-`.py` change still counts as code.
 */
export default defineTool({
  description:
    "Compare full-repo pytest results for base and head, read from the cloud-runner JUnit artifacts for those exact SHAs. Flake list is the committed known-flakes.txt. Records the result for this head. Carry-over needs a recorded clean SHA and a head that changed only prose or images.",
  inputSchema: z.object({
    headSha: Sha,
    baseSha: Sha.describe("The PR's base commit, as `check_gate_state` and the PR show it. Refused when it is not."),
    carryFromSha: Sha.optional().describe(
      "A prior head of this PR whose suite is already recorded clean, to carry from. Refused unless that record exists.",
    ),
  }),
  effect: "idempotent",
  dryRunResult: () => ({ recorded: false, reason: "dry-run", clean: false }),
  async execute(input, ctx) {
    const isEval = ctx.session.purpose === "eval";
    const fixture = isEval ? await readPrFixture(ctx.workspaceDir) : undefined;

    let changedFiles: string[];
    let currentHeadSha: string;
    let currentBaseSha: string | undefined;
    let prRef: { owner: string; repo: string; number: number } | undefined;

    if (isEval) {
      if (fixture === undefined) {
        throw new Error("eval session without a seeded pr.json");
      }
      changedFiles = fixture.files;
      currentHeadSha = fixture.headSha;
    } else {
      prRef = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
      if (prRef === undefined) {
        throw new Error("compare_suite_runs needs a GitHub pull request session");
      }
      const octokit = await ctx.host.github.getOctokit();
      const pr = await readPr(octokit, prRef);
      changedFiles = pr.files;
      currentHeadSha = pr.headSha;
      currentBaseSha = pr.baseSha;
    }

    if (currentHeadSha !== input.headSha) {
      // A comparison for a head that has been replaced would record a result
      // against a SHA nobody is reviewing.
      return { recorded: false, reason: "stale-head", current: currentHeadSha, clean: false };
    }

    // The base comes from the PR. A model that names the head, or an old commit
    // where the same tests already failed, turns every failure into "pre-existing".
    if (currentBaseSha !== undefined && input.baseSha !== currentBaseSha) {
      return {
        recorded: false,
        reason: "base-mismatch",
        expected: currentBaseSha,
        given: input.baseSha,
        carried: false,
        clean: false,
      };
    }

    // Carry-over: the head must have changed nothing a suite can observe, and
    // the SHA being carried from must itself have a recorded *clean* run.
    if (input.carryFromSha !== undefined) {
      const prior = isEval
        ? "clean"
        : ((await readSuiteRecord(ctx.host.kv, requirePr(prRef), input.carryFromSha))?.state ??
          "missing");
      const decision = carryDecision({
        changedFiles,
        recordedAtCarryFrom: prior,
      });

      if (!decision.ok && decision.reason === "code-changed") {
        return {
          recorded: false,
          reason: "code-changed",
          files: decision.blocking,
          carried: false,
          clean: false,
        };
      }
      if (!decision.ok) {
        // A carried result is only as good as an actual clean run at that SHA.
        // Accepting any SHA the caller names let a model invent one.
        return {
          recorded: false,
          reason: "no-clean-source",
          carryFromSha: input.carryFromSha,
          found: prior,
          carried: false,
          clean: false,
        };
      }

      if (!isEval) {
        await ctx.host.kv.put(suiteKey(requirePr(prRef), input.headSha), {
          state: "carried",
          carriedFrom: input.carryFromSha,
          at: Date.now(),
        });
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

    let baseXml: string;
    let headXml: string;
    let runner: { headRunId: number; baseRunId: number } | undefined;

    if (isEval) {
      // An eval has no runner and no network. The case's gate.json already
      // pins the suite state, so this path records nothing and claims nothing.
      return { recorded: false, reason: "eval-no-runner", carried: false, clean: false };
    }

    const octokit = await ctx.host.github.getOctokit();
    const repoRef = requirePr(prRef);
    const reader: Runner = octokitRunner(octokit, { owner: repoRef.owner, repo: repoRef.repo });

    const head = await fetchJunit(reader, input.headSha);
    if (!head.ok) {
      return { recorded: false, reason: `head-${head.reason}`, detail: head.detail, carried: false, clean: false };
    }
    const base = await fetchJunit(reader, input.baseSha);
    if (!base.ok) {
      return { recorded: false, reason: `base-${base.reason}`, detail: base.detail, carried: false, clean: false };
    }
    baseXml = base.xml;
    headXml = head.xml;
    runner = { headRunId: head.runId, baseRunId: base.runId };

    const flakes = knownFlakes();
    const diff = diffJunit({ baseXml, headXml, knownFlakes: flakes.ids });

    await ctx.host.kv.put(suiteKey(repoRef, input.headSha), {
      state: diff.clean && diff.invalid === undefined ? "clean" : "regressed",
      newFailures: diff.newFailures,
      runId: runner.headRunId,
      at: Date.now(),
    });

    return {
      recorded: true,
      carried: false,
      ...diff,
      runner,
      flakeList: flakes.source,
    };
  },
});
