import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr } from "../lib/gh.js";
import { redactSecrets } from "../lib/redact.js";
import { postVerdictComment } from "../lib/tag.js";

const Sha = z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA");

const SkillsTable = z
  .array(
    z.object({
      skill: z.string().min(1),
      used: z.boolean(),
      note: z.string().describe("What it found or changed, or `skipped: <reason>`."),
    }),
  )
  .min(1);

function renderTable(skills: { skill: string; used: boolean; note: string }[]): string {
  const rows = skills.map((s) => `| \`${s.skill}\` | ${s.used ? "yes" : "no"} | ${s.note} |`);
  return ["| Skill | Used | Found / changed |", "| --- | --- | --- |", ...rows].join("\n");
}

/**
 * Post MC's formal verdict for one head. Once per head.
 *
 * Refuses a stale head, stays silent in an eval session, and redacts before
 * anything leaves the process. The signature is fixed here rather than taken
 * from the model, so a post always says who posted it.
 */
export default defineTool({
  description:
    "Post MC's formal verdict for one head SHA on this session's PR. Call once per head. Refuses when the PR head has moved. The Skills table is required.",
  inputSchema: z.object({
    headSha: Sha,
    verdict: z.enum(["PASS", "MODIFY", "FAIL"]),
    body: z.string().min(1).describe("The review body: findings, severities, and measured/inferred labels."),
    skills: SkillsTable,
  }),
  effect: "write",
  dryRunResult: (input) => ({ posted: false, reason: "dry-run", verdict: input.verdict }),
  async execute(input, ctx) {
    if (ctx.session.purpose === "eval") {
      return { posted: false, reason: "eval", verdict: input.verdict };
    }

    const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
    if (ref === undefined) {
      throw new Error("post_verdict needs a GitHub pull request session");
    }

    const octokit = await ctx.host.github.getOctokit();
    const pr = await readPr(octokit, ref);
    if (pr.headSha !== input.headSha) {
      return { posted: false, reason: "stale-head", current: pr.headSha };
    }

    const composed = [
      `## MC verdict: **${input.verdict}** at \`${input.headSha}\``,
      "",
      input.body,
      "",
      "### Skills",
      "",
      renderTable(input.skills),
      "",
      "---",
      "",
      "_Posted by the subnet-dashboard review gate. Review only: this bot never merges, deploys, restarts, sets secrets or labels._",
    ].join("\n");

    const { text, redactedNames } = redactSecrets(composed);
    const result = await postVerdictComment({
      octokit,
      ref,
      headSha: input.headSha,
      currentHeadSha: pr.headSha,
      body: text,
    });

    await ctx.artifacts.tag({
      kind: "head-verdict",
      key: `${ref.number}@${input.headSha}`,
      title: `MC ${input.verdict} @ ${input.headSha.slice(0, 8)}`,
      data: {
        reviewer: "mc",
        verdict: input.verdict,
        headSha: input.headSha,
        pr: `${ref.owner}/${ref.repo}#${ref.number}`,
        redactedNames,
      },
    });

    return {
      posted: result.posted,
      reason: result.reason,
      commentId: result.commentId ?? null,
      redactedNames,
    };
  },
});
