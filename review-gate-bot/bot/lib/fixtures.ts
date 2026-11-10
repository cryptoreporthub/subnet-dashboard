import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { GateState } from "./gate.js";
import type { PrSnapshot } from "./gh.js";
import type { Diff, DiffFile } from "./repo.js";

/**
 * Eval sessions have no GitHub PR behind them: `continuationKey` is absent, so
 * `parseGitHubPrContinuationKey` returns undefined and a live read would throw.
 *
 * Rather than let every eval degrade into "the tool errored", an eval session
 * reads a pinned snapshot from its own workspace — the two files the eval case
 * seeds with `workspaceFiles`:
 *
 * - `pr.json`   — the PR at the head the case pins
 * - `gate.json` — the gate inputs for that head
 *
 * This is evidence preparation, not judgement: the fixtures are fixed, and the
 * gate logic still runs for real over them.
 */

export const PR_FIXTURE = "pr.json";
export const GATE_FIXTURE = "gate.json";
export const DIFF_FIXTURE = "diff.json";
export const REPO_FIXTURE = "repo.json";

export class FixtureMalformedError extends Error {
  readonly name = "FixtureMalformedError";

  constructor(
    readonly fixture: string,
    detail: string,
  ) {
    super(`${fixture}: ${detail}`);
  }
}

/**
 * A fixture that is not there means its case did not seed it. One that is there but unreadable or malformed
 * is a broken case, and it fails loudly: otherwise an eval session would run without the PR it claims to test.
 */
async function readJson<T>(workspaceDir: string, name: string): Promise<T | undefined> {
  let text: string;
  try {
    text = await readFile(join(workspaceDir, name), "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return undefined;
    }
    throw error;
  }
  return JSON.parse(text) as T;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseDiffFixture(name: string, value: unknown): Diff {
  if (typeof value !== "object" || value === null) {
    throw new FixtureMalformedError(name, "expected an object");
  }
  const record = value as Record<string, unknown>;
  if (typeof record.totalFiles !== "number") {
    throw new FixtureMalformedError(name, "totalFiles must be a number");
  }
  if (!Array.isArray(record.files)) {
    throw new FixtureMalformedError(name, "files must be an array");
  }
  if (typeof record.truncated !== "boolean") {
    throw new FixtureMalformedError(name, "truncated must be a boolean");
  }
  if (!isStringArray(record.omittedPaths)) {
    throw new FixtureMalformedError(name, "omittedPaths must be an array of strings");
  }
  const files = record.files.map((file, index) => {
    if (typeof file !== "object" || file === null) {
      throw new FixtureMalformedError(name, `files[${index}] must be an object`);
    }
    const entry = file as Record<string, unknown>;
    if (typeof entry.path !== "string") {
      throw new FixtureMalformedError(name, `files[${index}].path must be a string`);
    }
    if (typeof entry.status !== "string") {
      throw new FixtureMalformedError(name, `files[${index}].status must be a string`);
    }
    if (typeof entry.additions !== "number" || typeof entry.deletions !== "number") {
      throw new FixtureMalformedError(name, `files[${index}] additions and deletions must be numbers`);
    }
    const diffFile: DiffFile = {
      path: entry.path,
      status: entry.status,
      additions: entry.additions,
      deletions: entry.deletions,
    };
    if (entry.previousPath !== undefined) {
      if (typeof entry.previousPath !== "string") {
        throw new FixtureMalformedError(name, `files[${index}].previousPath must be a string`);
      }
      diffFile.previousPath = entry.previousPath;
    }
    if (entry.patch !== undefined) {
      if (typeof entry.patch !== "string") {
        throw new FixtureMalformedError(name, `files[${index}].patch must be a string`);
      }
      diffFile.patch = entry.patch;
    }
    if (entry.patchOmitted !== undefined) {
      if (typeof entry.patchOmitted !== "string") {
        throw new FixtureMalformedError(name, `files[${index}].patchOmitted must be a string`);
      }
      diffFile.patchOmitted = entry.patchOmitted;
    }
    return diffFile;
  });
  return {
    totalFiles: record.totalFiles,
    files,
    truncated: record.truncated,
    omittedPaths: record.omittedPaths,
  };
}

/** The PR a fixture describes, or undefined when the case did not seed one. */
export function readPrFixture(workspaceDir: string): Promise<PrSnapshot | undefined> {
  return readJson<PrSnapshot>(workspaceDir, PR_FIXTURE);
}

export type GateFixture = {
  headSha: string;
  mc: GateState["mc"];
  cursor: GateState["cursor"];
  ditto: GateState["ditto"];
  replit: GateState["replit"];
  suite: GateState["suite"];
  replitTagged: boolean;
  next: GateState["next"];
};

export function readGateFixture(workspaceDir: string): Promise<GateFixture | undefined> {
  return readJson<GateFixture>(workspaceDir, GATE_FIXTURE);
}

/** The PR's diff as the case pins it, or undefined when the case did not seed one. */
export async function readDiffFixture(workspaceDir: string): Promise<Diff | undefined> {
  const raw = await readJson<unknown>(workspaceDir, DIFF_FIXTURE);
  if (raw === undefined) {
    return undefined;
  }
  return parseDiffFixture(DIFF_FIXTURE, raw);
}

/** File contents at the pinned head: `{ "files": { "<path>": "<text>" } }`. */
export function readRepoFixture(workspaceDir: string): Promise<{ files: Record<string, string> } | undefined> {
  return readJson<{ files: Record<string, string> }>(workspaceDir, REPO_FIXTURE);
}
