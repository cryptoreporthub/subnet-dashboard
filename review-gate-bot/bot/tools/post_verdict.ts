import { defineTool } from "@grok/agent-sdk/tools";
import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { z } from "zod";
import { readPr } from "../lib/gh.js";
import { redactSecrets } from "../lib/redact.js";
import { postVerdictComment } from "../lib/tag.js";

const Sha = z.string().regex(/^[0-9a-f]{40}$/, "a full 40-character head SHA");

/**
 * Findings that rule out a PASS whatever severity the review gave them. The
 * model declares them; the tool enforces the consequence, because a verdict is
 * a side effect and the code owns side-effect gates.
 */
const BLOCKING_KINDS = ["never-expires", "overflow", "aborts-cycle", "poisons-later-row"] as const;

const SkillsTable = z
  .array(
    z.object({
      skill: z.string().min(1),
      used: z.boolean(),
      note: z.string().describe("What it found or changed, or `skipped: <reason>`."),
    }),
  )
  .min(1);

/** Every review must account for all three on-demand skills, even when skipped. */
const REQUIRED_SKILLS = ["adversarial-review", "owner-rules", "settled-check"] as const;

function missingRequiredSkills(skills: { skill: string }[]): string[] {
  const names = new Set(skills.map((s) => s.skill.trim()));
  return REQUIRED_SKILLS.filter((name) => !names.has(name));
}

/** A PASS must not ship prose that still carries a credential-shaped value after scrubbing. */
function passLeaksCredential(text: string): boolean {
  const { text: scrubbed } = redactSecrets(text);
  return scrubbed !== text;
}

function skillsIncomplete(skills: { skill: string; used: boolean; note: string }[]): string | undefined {
  const missing = missingRequiredSkills(skills);
  if (missing.length > 0) {
    return missing.join(", ");
  }
  for (const row of skills) {
    if (row.used && row.note.trim().length < 8) {
      return row.skill;
    }
    if (row.used && /^skipped:/i.test(row.note.trim())) {
      return row.skill;
    }
  }
  return undefined;
}

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
 * Refuses a PASS that declares a blocking finding, refuses a stale head, stays
 * silent in an eval session, and redacts before anything leaves the process. The signature is fixed here rather than taken
 * from the model, so a post always says who posted it.
 *
 */
export default defineTool({
  description:
    "Post MC's formal verdict for one head SHA on this session's PR. Call once per head. Refuses when the PR head has moved, and refuses a PASS while any blocking finding is declared: resubmit as MODIFY or FAIL. The Skills table is required.",
  inputSchema: z.object({
    headSha: Sha,
    verdict: z.enum(["PASS", "MODIFY", "FAIL"]),
    body: z.string().min(1).describe("The review body: findings, severities, and measured/inferred labels."),
    skills: SkillsTable,
    blocking: z
      .array(z.enum(BLOCKING_KINDS))
      .optional()
      .describe(
        "Every finding that makes rows never expire (`never-expires`), lets a value overflow to inf or NaN (`overflow`), lets a cycle or a later row abort (`aborts-cycle`), or writes bad state that later cycles read back (`poisons-later-row`). Declare each one whatever its severity. PASS is refused while any is declared.",
      ),
  }),
  effect: "write",
  dryRunResult: (input) => ({ posted: false, reason: "dry-run", verdict: input.verdict }),
  async execute(input, ctx) {
    const blocking = input.blocking ?? [];
    if (input.verdict === "PASS" && blocking.length > 0) {
      return { posted: false, reason: "pass-with-blocking-finding", verdict: input.verdict, blocking };
    }

    const incompleteSkill = skillsIncomplete(input.skills);
    if (incompleteSkill !== undefined) {
      return { posted: false, reason: "incomplete-skills-table", verdict: input.verdict, skill: incompleteSkill };
    }

    const composed = composeVerdictBody({
      verdict: input.verdict,
      headSha: input.headSha,
      body: input.body,
      skills: input.skills,
    });
    if (input.verdict === "PASS" && passLeaksCredential(composed)) {
      return { posted: false, reason: "pass-with-credential-value", verdict: input.verdict };
    }

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

    const { text, redactedNames } = redactSecrets(composed);

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
