import type { HostKvApi } from "@grok/agent-sdk/kv";

/**
 * Which of the bot's own skills a session actually opened.
 *
 * The Skills table in a verdict says which skills the review used. A model can write `used: true` for a
 * skill it never read (hard exam r4: 16 runs read no skill file and still marked all three as used, and two
 * of them missed exactly the owner rule that skill states). The table is a claim about what happened, so the
 * code checks it: a `Read` of `.../skills/<name>/SKILL.md` is recorded as it is requested (`bot/hooks/skill-reads.ts`),
 * and `post_verdict` refuses `used: true` for a skill with no record.
 *
 * The record is per session in the host kv, so it survives neither another session's turn nor a process
 * restart that loses the kv, and a kv that cannot be read lets the post through (see `unreadSkills`).
 */

/** The skills this bot ships in `bot/skills/`. A table row naming anything else is not checked. */
export const SKILL_NAMES = ["adversarial-review", "owner-rules", "settled-check", "outside-commenter"] as const;

export type SkillName = (typeof SKILL_NAMES)[number];

const KEY_PREFIX = "skill-reads:";

export const skillReadsKey = (sessionId: string): string => `${KEY_PREFIX}${sessionId}`;

/** The skill a `Read` path opens, or undefined for any other path. Matches the sandboxed workspace path the model sees. */
export function skillNameFromReadPath(path: unknown): SkillName | undefined {
  if (typeof path !== "string") {
    return undefined;
  }
  const match = /(?:^|\/)skills\/([a-z][a-z-]*)\/SKILL\.md$/.exec(path.trim());
  const name = match?.[1];
  return SKILL_NAMES.find((known) => known === name);
}

/** A Skills table row's name, reduced to what it names: `\`owner-rules\`` and `Owner-Rules` both mean `owner-rules`. */
export function skillNameFromRow(skill: string): SkillName | undefined {
  const bare = skill.toLowerCase().replace(/[^a-z-]/g, "");
  return SKILL_NAMES.find((known) => known === bare);
}

type Call = { toolName?: string; args?: unknown; parentCallId?: string };

/** The skills opened by the main turn's `Read` calls in one `actions.requested` batch. */
export function skillsOpenedBy(calls: readonly Call[]): SkillName[] {
  const opened: SkillName[] = [];
  for (const call of calls) {
    if (call.parentCallId !== undefined || call.toolName?.toLowerCase() !== "read") {
      continue;
    }
    const args = call.args as { path?: unknown; file_path?: unknown } | undefined;
    const name = skillNameFromReadPath(args?.path ?? args?.file_path);
    if (name !== undefined && !opened.includes(name)) {
      opened.push(name);
    }
  }
  return opened;
}

export async function recordSkillReads(kv: Pick<HostKvApi, "get" | "put">, sessionId: string, names: readonly SkillName[]): Promise<void> {
  if (names.length === 0) {
    return;
  }
  const seen = new Set<string>(((await kv.get(skillReadsKey(sessionId))) as string[] | undefined) ?? []);
  for (const name of names) {
    seen.add(name);
  }
  await kv.put(skillReadsKey(sessionId), [...seen].sort());
}

/**
 * The skills a Skills table calls `used` that this session never opened.
 *
 * `used: false` rows are never checked: `skipped: <reason>` is the honest way out. A kv that throws is
 * infrastructure, not a model fault, so it lets the post through rather than blocking a verdict on storage.
 */
export async function unreadSkills(
  kv: Pick<HostKvApi, "get">,
  sessionId: string,
  skills: readonly { skill: string; used: boolean }[],
): Promise<SkillName[]> {
  const claimed = new Set<SkillName>();
  for (const row of skills) {
    const name = skillNameFromRow(row.skill);
    if (row.used && name !== undefined) {
      claimed.add(name);
    }
  }
  if (claimed.size === 0) {
    return [];
  }
  let seen: Set<string>;
  try {
    seen = new Set(((await kv.get(skillReadsKey(sessionId))) as string[] | undefined) ?? []);
  } catch {
    return [];
  }
  return [...claimed].filter((name) => !seen.has(name));
}
