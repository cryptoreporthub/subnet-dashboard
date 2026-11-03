import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BOT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

function stripFrontmatter(markdown: string): string {
  if (!markdown.startsWith("---")) {
    return markdown.trim();
  }
  const end = markdown.indexOf("---", 3);
  return end === -1 ? markdown.trim() : markdown.slice(end + 3).trim();
}

function loadSkillBody(name: string): string {
  return stripFrontmatter(readFileSync(join(BOT_ROOT, "skills", name, "SKILL.md"), "utf8"));
}

/** R2 method arms: arms differ only via `bot/instructions.ts` markdown. */
export type MethodArm = "none" | "owner-adv5" | "all-three";

export const METHOD_ARMS: readonly MethodArm[] = ["none", "owner-adv5", "all-three"];

function extractSection(markdown: string, heading: string): string {
  const needle = `## ${heading}`;
  const start = markdown.indexOf(needle);
  if (start === -1) {
    return "";
  }
  const rest = markdown.slice(start + needle.length);
  const next = rest.search(/\n## /);
  const body = next === -1 ? rest : rest.slice(0, next);
  return `## ${heading}${body}`.trim();
}

/** Markdown body for `defineInstructions` (excludes `bot/instructions.md`, which the SDK joins separately). */
export function reviewMethodMarkdownForArm(arm: MethodArm): string {
  if (arm === "none") {
    return "";
  }
  if (arm === "owner-adv5") {
    const owner = loadSkillBody("owner-rules");
    const adv = loadSkillBody("adversarial-review");
    const section5 = extractSection(adv, "5. Hunt for one bug the PR does not mention");
    return [
      "## Always-loaded review method (R2 arm: owner-adv5)",
      "",
      "### owner-rules",
      "",
      owner,
      "",
      "### adversarial-review (section 5 only)",
      "",
      section5,
    ].join("\n");
  }
  const adv = loadSkillBody("adversarial-review");
  const owner = loadSkillBody("owner-rules");
  const settled = loadSkillBody("settled-check");
  return [
    "## Always-loaded review method (R2 arm: all-three)",
    "",
    "The three core skills below are inlined here so every turn receives them without opening SKILL.md files.",
    "Mark them `used: true` in the Skills table when you applied them; you do not need a separate Read of these files.",
    "",
    "### adversarial-review",
    "",
    adv,
    "",
    "### owner-rules",
    "",
    owner,
    "",
    "### settled-check",
    "",
    settled,
  ].join("\n");
}

export function methodArmFromEnv(): MethodArm {
  const raw = (process.env.R2_METHOD_ARM ?? "all-three").trim();
  if ((METHOD_ARMS as readonly string[]).includes(raw)) {
    return raw as MethodArm;
  }
  return "all-three";
}

export function instructionsVariantManifest(baseInstructionsMd: string): Record<
  MethodArm,
  { sha256: string; composedChars: number; methodChars: number }
> {
  const base = baseInstructionsMd.trim();
  const out = {} as Record<MethodArm, { sha256: string; composedChars: number; methodChars: number }>;
  for (const arm of METHOD_ARMS) {
    const method = reviewMethodMarkdownForArm(arm);
    const composed = method ? `${base}\n\n${method}` : base;
    out[arm] = {
      sha256: createHash("sha256").update(composed, "utf8").digest("hex"),
      composedChars: composed.length,
      methodChars: method.length,
    };
  }
  return out;
}
