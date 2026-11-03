import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  OWNER_RULES_ALWAYS_IN_FORCE_BLOCK,
  R23_SUITE_SHRINK_VERDICT_RULE,
  REVIEWER_STATE_FROM_GATE_BLOCK,
  prHeadInstructionsMarkdown,
} from "./instruction-blocks.js";

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

/** R2 method arms on PR-head instructions.md (50e231f3); only `bot/instructions.ts` append differs. */
export type MethodArm = "A" | "B" | "C" | "D" | "R";

/** Full exam arm from env, including F (unredacted eval reads only; instructions stay arm A). */
export type R2MethodArm = MethodArm | "F";

export type SessionPurpose = "eval" | "live";

export const METHOD_ARMS: readonly MethodArm[] = ["A", "B", "C", "D", "R"];

const R2_ARM_ENV: Record<string, R2MethodArm> = {
  A: "A",
  a: "A",
  none: "A",
  F: "F",
  f: "F",
  "unredacted-reads": "F",
  B: "B",
  b: "B",
  "owner-rules": "B",
  C: "C",
  c: "C",
  "all-three": "C",
  D: "D",
  d: "D",
  "r4-bundle": "D",
  R: "R",
  r: "R",
  r23: "R",
  "suite-shrink": "R",
};

/** Markdown appended via `defineInstructions` (SDK joins after `bot/instructions.md`). */
export function reviewMethodMarkdownForArm(arm: MethodArm): string {
  if (arm === "A") {
    return "";
  }
  if (arm === "B") {
    return OWNER_RULES_ALWAYS_IN_FORCE_BLOCK;
  }
  if (arm === "C") {
    const adv = loadSkillBody("adversarial-review");
    const owner = loadSkillBody("owner-rules");
    const settled = loadSkillBody("settled-check");
    return [
      "## Always-loaded review method (R2 arm C)",
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
  if (arm === "R") {
    return R23_SUITE_SHRINK_VERDICT_RULE;
  }
  return [OWNER_RULES_ALWAYS_IN_FORCE_BLOCK, "", REVIEWER_STATE_FROM_GATE_BLOCK].join("\n");
}

export function r2MethodArmFromEnv(): R2MethodArm {
  const raw = (process.env.R2_METHOD_ARM ?? "A").trim();
  return R2_ARM_ENV[raw] ?? "A";
}

/** Instruction append arm: F is prompt-neutral (maps to A). */
export function methodArmFromEnv(): MethodArm {
  const arm = r2MethodArmFromEnv();
  return arm === "F" ? "A" : arm;
}

export function instructionsVariantManifest(): Record<
  MethodArm,
  {
    sha256: string;
    composedChars: number;
    appendChars: number;
    baseChars: number;
    baseSha: string;
  }
> {
  const base = prHeadInstructionsMarkdown();
  const baseSha = createHash("sha256").update(base, "utf8").digest("hex");
  const out = {} as Record<
    MethodArm,
    { sha256: string; composedChars: number; appendChars: number; baseChars: number; baseSha: string }
  >;
  for (const arm of METHOD_ARMS) {
    const append = reviewMethodMarkdownForArm(arm);
    const composed = append ? `${base}\n\n${append}` : base;
    out[arm] = {
      baseSha,
      baseChars: base.length,
      appendChars: append.length,
      composedChars: composed.length,
      sha256: createHash("sha256").update(composed, "utf8").digest("hex"),
    };
  }
  return out;
}
