import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { methodArmFromEnv, reviewMethodMarkdownForArm } from "./method-variants.js";

const BOT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Skills whose full SKILL.md body is appended to the system prompt via `bot/instructions.ts`. */
export const ALWAYS_DELIVERED_SKILLS = ["adversarial-review", "owner-rules", "settled-check"] as const;

export type AlwaysDeliveredSkill = (typeof ALWAYS_DELIVERED_SKILLS)[number];

export function isAlwaysDeliveredSkill(name: string): boolean {
  return (ALWAYS_DELIVERED_SKILLS as readonly string[]).includes(name);
}

function stripFrontmatter(markdown: string): string {
  if (!markdown.startsWith("---")) {
    return markdown.trim();
  }
  const end = markdown.indexOf("---", 3);
  return end === -1 ? markdown.trim() : markdown.slice(end + 3).trim();
}

export function loadSkillBody(name: AlwaysDeliveredSkill | string): string {
  return stripFrontmatter(readFileSync(join(BOT_ROOT, "skills", name, "SKILL.md"), "utf8"));
}

/** Markdown appended after `bot/instructions.md` so the review method is always in the system prompt. */
export function reviewMethodMarkdown(): string {
  return reviewMethodMarkdownForArm(methodArmFromEnv());
}

/** Deterministic anchors: if any is missing, the method was not delivered. */
export const METHOD_DELIVERY_ANCHORS = [
  "## 3b. Estimating cost you cannot time",
  "## 1. Picks readers serve only complete snapshots",
  "Before you raise a finding, spend one pass asking whether it is already",
] as const;

export function systemPromptIncludesMethod(text: string): boolean {
  return METHOD_DELIVERY_ANCHORS.every((anchor) => text.includes(anchor));
}
