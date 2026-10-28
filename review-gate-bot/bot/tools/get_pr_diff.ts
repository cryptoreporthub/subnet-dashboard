import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr } from "../lib/gh.js";
import { readDiffFixture, readPrFixture } from "../lib/fixtures.js";
import { readDiff } from "../lib/repo.js";

/**
 * The change itself: each file's patch, for the head the review is about.
 *
 * Read-only. The PR comes from the session, the head is checked against the live
 * PR, and patches are scrubbed of secret-shaped values and capped in size.
 */
export default defineTool({
  description:
    "Read this PR's diff: path, status, counts and patch per changed file. Pass the head SHA from check_gate_state; refused if the head has moved. Name paths to read only some files. A cut or missing patch is flagged; read the file at head instead. A diff of 300 or more files is refused: read the files you need at head.",
  inputSchema: z.object({
    headSha: z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA"),
    paths: z.array(z.string().min(1).max(300)).max(50).optional().describe("Only these changed files."),
  }),
  effect: "read",
  async execute(input, ctx) {
    if (ctx.session.purpose === "eval") {
      const [pr, diff] = await Promise.all([readPrFixture(ctx.workspaceDir), readDiffFixture(ctx.workspaceDir)]);
      if (pr !== undefined && pr.headSha !== input.headSha) {
        return { ok: false, reason: "stale-head", current: pr.headSha };
      }
      if (diff === undefined) {
        return { ok: false, reason: "no diff in this fixture" };
      }
      const wanted = input.paths === undefined ? undefined : new Set(input.paths);
      const files = wanted === undefined ? diff.files : diff.files.filter((file) => wanted.has(file.path));
      return { ok: true, ...diff, files, source: "fixture" };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("get_pr_diff needs a GitHub pull request session");
    }
    const octokit = await ctx.host.github.getOctokit();
    const pr = await readPr(octokit, ref);
    if (pr.headSha !== input.headSha) {
      return { ok: false, reason: "stale-head", current: pr.headSha };
    }
    const diff = await readDiff(octokit, ref, { head: pr.headSha, base: pr.baseSha, paths: input.paths });
    return diff.ok ? { ...diff, source: "github" } : diff;
  },
});
