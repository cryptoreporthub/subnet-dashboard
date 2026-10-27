import type { Octokit } from "@octokit/rest";
import type { PrRef } from "./gh.js";
import { redactSecrets } from "./redact.js";

/**
 * Read-only views of the repository for the reviewer.
 *
 * The model has no built-in tools, so these are its only eyes. Every read is
 * pinned to a commit the PR itself names (its head or its base), never a ref the
 * model chose, and every byte that leaves passes the secret scrubber. Output is
 * capped so one large file cannot fill a turn, and a cut is always flagged:
 * a silent cut would read as "that is all there is".
 */

export const LIMITS = {
  diffChars: 120_000,
  fileChars: 60_000,
  listEntries: 2_000,
  pathChars: 300,
} as const;

/** A repo-relative path with no way out of the repo. */
export function validRepoPath(path: string): boolean {
  if (path === "" || path.length > LIMITS.pathChars) {
    return false;
  }
  if (path.startsWith("/") || path.includes("\\") || path.includes("\0")) {
    return false;
  }
  return !path.split("/").some((part) => part === ".." || part === "");
}

export type DiffFile = {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  previousPath?: string;
  patch?: string;
  patchOmitted?: string;
};

export type Diff = {
  totalFiles: number;
  files: DiffFile[];
  truncated: boolean;
  omittedPaths: string[];
};

export async function readDiff(octokit: Octokit, ref: PrRef, options: { paths?: string[] }): Promise<Diff> {
  const all = await octokit.paginate(octokit.rest.pulls.listFiles, {
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
    per_page: 100,
  });
  const wanted = options.paths === undefined ? undefined : new Set(options.paths);
  const files: DiffFile[] = [];
  const omittedPaths: string[] = [];
  let budget = LIMITS.diffChars;

  for (const file of all) {
    if (wanted !== undefined && !wanted.has(file.filename)) {
      continue;
    }
    const entry: DiffFile = {
      path: file.filename,
      status: file.status,
      additions: file.additions,
      deletions: file.deletions,
    };
    if (file.previous_filename !== undefined) {
      entry.previousPath = file.previous_filename;
    }
    if (file.patch === undefined) {
      entry.patchOmitted = "GitHub gave no patch: the file is binary or too large to diff";
    } else if (file.patch.length > budget) {
      entry.patchOmitted = `over the remaining size budget (${file.patch.length} chars); read the file at head instead`;
      omittedPaths.push(file.filename);
    } else {
      entry.patch = redactSecrets(file.patch).text;
      budget -= file.patch.length;
    }
    files.push(entry);
  }

  return {
    totalFiles: wanted === undefined ? all.length : files.length,
    files,
    truncated: omittedPaths.length > 0,
    omittedPaths,
  };
}

export type FileRead =
  | {
      ok: true;
      path: string;
      sha: string;
      text: string;
      startLine: number;
      endLine: number;
      totalLines: number;
      truncated: boolean;
    }
  | { ok: false; path: string; reason: string };

function refusal(path: string, reason: string): FileRead {
  return { ok: false, path, reason };
}

export type TextWindow = {
  text: string;
  startLine: number;
  endLine: number;
  totalLines: number;
  truncated: boolean;
};

/**
 * The lines a reader asked for, scrubbed and then capped. Live and eval reads both
 * go through here, so they cannot disagree about what leaves.
 *
 * Scrubbing comes before the cap. Cutting first can leave the head of a secret at
 * the cap, and the scrubber does not match a head, so it would go out in the clear.
 */
export function windowText(content: string, options: { startLine?: number; endLine?: number }): TextWindow {
  const lines = content.split("\n");
  const startLine = Math.max(1, options.startLine ?? 1);
  const endLine = Math.min(lines.length, options.endLine ?? lines.length);
  const scrubbed = redactSecrets(lines.slice(startLine - 1, endLine).join("\n")).text;
  const truncated = scrubbed.length > LIMITS.fileChars;
  const text = truncated ? scrubbed.slice(0, LIMITS.fileChars) : scrubbed;
  return {
    text,
    startLine,
    endLine: truncated ? startLine + text.split("\n").length - 1 : endLine,
    totalLines: lines.length,
    truncated,
  };
}

export async function readRepoFile(
  octokit: Octokit,
  ref: PrRef,
  sha: string,
  path: string,
  options: { startLine?: number; endLine?: number },
): Promise<FileRead> {
  if (!validRepoPath(path)) {
    return refusal(path, "not a repo-relative path");
  }

  let data: unknown;
  try {
    ({ data } = await octokit.rest.repos.getContent({ owner: ref.owner, repo: ref.repo, path, ref: sha }));
  } catch (error) {
    const status = (error as { status?: number }).status;
    return refusal(path, status === 404 ? "not found at this commit" : `could not read: ${(error as Error).message}`);
  }

  if (Array.isArray(data)) {
    return refusal(path, "is a directory; use list_repo_files");
  }
  const entry = data as { type?: string; encoding?: string; content?: string; size?: number };
  if (entry.type !== "file") {
    return refusal(path, `is a ${entry.type ?? "non-file"}, which is not read`);
  }
  if (entry.encoding !== "base64" || typeof entry.content !== "string") {
    return refusal(path, `too large for the contents API (${entry.size ?? "unknown"} bytes)`);
  }

  return {
    ok: true,
    path,
    sha,
    ...windowText(Buffer.from(entry.content, "base64").toString("utf8"), options),
  };
}

export type Listing = { sha: string; paths: string[]; truncated: boolean };

export async function listRepoFiles(
  octokit: Octokit,
  ref: PrRef,
  sha: string,
  options: { prefix?: string },
): Promise<Listing> {
  const { data } = await octokit.rest.git.getTree({ owner: ref.owner, repo: ref.repo, tree_sha: sha, recursive: "1" });
  const prefix = options.prefix ?? "";
  const matching = data.tree
    .filter((node) => node.type === "blob" && typeof node.path === "string" && node.path.startsWith(prefix))
    .map((node) => node.path as string);
  return {
    sha,
    paths: matching.slice(0, LIMITS.listEntries),
    truncated: Boolean(data.truncated) || matching.length > LIMITS.listEntries,
  };
}
