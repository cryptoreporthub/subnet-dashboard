import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr } from "../lib/gh.js";
import { readPrFixture, readRepoFixture } from "../lib/fixtures.js";
import { listRepoFiles } from "../lib/repo.js";

/**
 * Which files exist, at the PR's head or its base. Lets the reviewer find the
 * consumers of a value the diff changes, and see what a change deleted.
 */
export default defineTool({
  description:
    "List repository files at this PR's head or base commit, optionally under a path prefix such as `internal/council/`. The commit is the PR's own, never a ref you choose. A cut listing is flagged; narrow the prefix.",
  inputSchema: z.object({
    at: z.enum(["head", "base"]).describe("`head` is the code under review; `base` is what it replaces."),
    prefix: z.string().max(300).optional(),
  }),
  effect: "read",
  async execute(input, ctx) {
    if (ctx.session.purpose === "eval") {
      const [pr, repo] = await Promise.all([readPrFixture(ctx.workspaceDir), readRepoFixture(ctx.workspaceDir)]);
      if (pr === undefined || repo === undefined) {
        return { ok: false, reason: "no repository in this fixture" };
      }
      const prefix = input.prefix ?? "";
      const paths = Object.keys(repo.files).filter((path) => path.startsWith(prefix));
      return { ok: true, sha: input.at === "head" ? pr.headSha : pr.baseSha, paths, truncated: false, source: "fixture" };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("list_repo_files needs a GitHub pull request session");
    }
    const octokit = await ctx.host.github.getOctokit();
    const pr = await readPr(octokit, ref);
    const sha = input.at === "head" ? pr.headSha : pr.baseSha;
    return { ok: true, ...(await listRepoFiles(octokit, ref, sha, { prefix: input.prefix })), source: "github" };
  },
});
