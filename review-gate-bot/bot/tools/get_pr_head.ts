import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { readPr } from "../lib/gh.js";
import { readPrFixture } from "../lib/fixtures.js";

/**
 * Read the PR this session is bound to.
 *
 * The PR comes from the session's continuation key, never from a model-supplied
 * identifier, so the model cannot point a review or a comment at another PR.
 * In an eval session there is no GitHub PR: the case seeds `pr.json` instead.
 */
export default defineTool({
  description:
    "Read this session's pull request: head SHA, base SHA, changed files, draft flag. Always call this first and review only the head SHA it returns.",
  effect: "read",
  async execute(_input, ctx) {
    if (ctx.session.purpose === "eval") {
      const fixture = await readPrFixture(ctx.workspaceDir);
      if (fixture === undefined) {
        throw new Error("eval session without a seeded pr.json");
      }
      return {
        number: fixture.number,
        headSha: fixture.headSha,
        baseSha: fixture.baseSha,
        draft: fixture.draft,
        title: fixture.title,
        url: fixture.url,
        fileCount: fixture.files.length,
        files: fixture.files,
        source: "fixture",
      };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("get_pr_head needs a GitHub pull request session");
    }
    const octokit = await ctx.host.github.getOctokit();
    const pr = await readPr(octokit, ref);
    return {
      number: pr.number,
      headSha: pr.headSha,
      baseSha: pr.baseSha,
      draft: pr.draft,
      title: pr.title,
      url: pr.url,
      fileCount: pr.files.length,
      files: pr.files,
      source: "github",
    };
  },
});
