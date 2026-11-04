import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../..");

/** Static deploy surfaces checked by `tests/production-config.test.ts`. */
export const PRODUCTION_R2_METHOD_ARM_CHECK_PATHS = {
  subnetDashboardFlyToml: join(REPO_ROOT, "fly.toml"),
  reviewGateAgent: join(dirname(fileURLToPath(import.meta.url)), "../agent.ts"),
} as const;

const R2_METHOD_ARM_PATTERN = /R2_METHOD_ARM/;

/**
 * Hosted live runtime: exam arm env must not be set (eval harness sets it locally only).
 * Called from the GitHub channel on each live delivery; see `bot/channels/github.ts`.
 */
export function assertHostedLiveHasNoExamArmEnv(): void {
  const raw = process.env.R2_METHOD_ARM?.trim();
  if (raw === undefined || raw === "" || raw.toUpperCase() === "A") {
    return;
  }
  throw new Error(
    `R2_METHOD_ARM=${JSON.stringify(raw)} must not be set on hosted live review-gate (eval-only exam arms; arm F is gated to eval sessions in code)`,
  );
}

/** Returns file paths that mention R2_METHOD_ARM in repo deploy config (empty = ok). */
export function deployFilesMentioningR2MethodArm(): string[] {
  const hits: string[] = [];
  for (const [label, path] of Object.entries(PRODUCTION_R2_METHOD_ARM_CHECK_PATHS)) {
    const text = readFileSync(path, "utf8");
    if (R2_METHOD_ARM_PATTERN.test(text)) {
      hits.push(`${label}: ${path}`);
    }
  }
  return hits;
}
