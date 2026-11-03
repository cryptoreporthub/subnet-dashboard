import { isAlwaysDeliveredSkill } from "./review-method.js";
import type { SkillName } from "./skill-reads.js";
import { skillNameFromRow } from "./skill-reads.js";

/**
 * Skills claimed `used: true` that were neither opened (Read of SKILL.md) nor delivered inline.
 * Used by `post_verdict` for skills-table integrity (R0 / PLAN-v1.1).
 */
export function skillsUsedWithoutDelivery(
  skills: readonly { skill: string; used: boolean }[],
  opened: ReadonlySet<string>,
): SkillName[] {
  const missing: SkillName[] = [];
  for (const row of skills) {
    if (!row.used) {
      continue;
    }
    const name = skillNameFromRow(row.skill);
    if (name === undefined) {
      continue;
    }
    if (opened.has(name) || isAlwaysDeliveredSkill(name)) {
      continue;
    }
    missing.push(name);
  }
  return missing;
}
