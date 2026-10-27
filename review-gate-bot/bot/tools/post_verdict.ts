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
 * The body a reader — and the gate itself — sees. Exported so the gate's
 * read-back test starts from exactly the text this tool posts.
 *
 * The first line is the verdict token. `parseVerdictToken` reads the first
 * line only, so this line is the verdict and nothing above it is prose.
 */
/**
 * Model-written text with every gate marker defused.
 *
 * The poster adds the one marker a verdict comment carries. A marker the model
 * wrote (it can come from a PR body or a comment it was asked to review) would
 * be read back as a tag for another slot, so Cursor and Ditto would never be
 * tagged, or as a second mc-verdict marker, which makes the comment unreadable.
 */
function withoutMarkers(text: string): string {
  return text.replace(/<!--\s*subnet-review-gate:/gi, "[marker removed]<!-- ");
}

export function composeVerdictBody(input: {
  verdict: "PASS" | "MODIFY" | "FAIL";
  headSha: string;
  body: string;
  skills: { skill: string; used: boolean; note: string }[];
}): string {
  return [
    `MC: **${input.verdict}** at \`${input.headSha}\``,
    "",
    withoutMarkers(input.body),
    "",
    "### Skills",
    "",
    renderTable(input.skills.map((s) => ({ ...s, skill: withoutMarkers(s.skill), note: withoutMarkers(s.note) }))),
    "",
    "---",
    "",
    "_Posted by the subnet-dashboard review gate. Review only: this bot never merges, deploys, restarts, sets secrets or labels._",
  ].join("\n");
}

/**
 * Post MC's formal verdict for one head. At most once per head, best effort.
 *
 * Refuses a stale head, stays silent in an eval session, and redacts before
 * anything leaves the process. The signature is fixed here rather than taken
 * from the model, so a post always says who posted it.
 *
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
    // Re-read immediately before posting: this is the head the guard compares
    // against, not one read earlier in the turn.
    const pr = await readPr(octokit, ref);
    if (pr.headSha !== input.headSha) {
      return { posted: false, reason: "stale-head", current: pr.headSha };
    }

    const { text, redactedNames } = redactSecrets(
      composeVerdictBody({
        verdict: input.verdict,
        headSha: input.headSha,
        body: input.body,
        skills: input.skills,
      }),
    );

    const result = await postVerdictComment({
      octokit,
      kv: ctx.host.kv,
      ref,
      headSha: input.headSha,
      currentHeadSha: pr.headSha,
      body: text,
    });

    return {
      posted: result.posted,
      reason: result.reason,
      commentId: result.commentId ?? null,
      redactedNames,
    };
  },
});
