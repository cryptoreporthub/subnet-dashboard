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

/** GitHub caps a compare's file list. A list at the cap may be cut short, so it cannot be read as whole. */
export const DIFF_FILE_CAP = 300;

export type DiffRead = ({ ok: true } & Diff) | { ok: false; reason: "diff-incomplete"; detail: string };

/**
 * The PR's diff between two commits the caller has already checked. The compare is pinned to
 * `base...head` by SHA, not read by PR number: `pulls.listFiles` answers for whatever head the PR
 * has at the moment of the call, so a push after the head check would hand back another head's
 * patches. A diff at the file cap is refused, since a cut list would read as the whole change.
 */
export async function readDiff(
  octokit: Octokit,
  ref: PrRef,
  options: { head: string; base: string; paths?: string[] },
): Promise<DiffRead> {
  const { data } = await octokit.rest.repos.compareCommitsWithBasehead({
    owner: ref.owner,
    repo: ref.repo,
    basehead: `${options.base}...${options.head}`,
  });
  const all = data.files ?? [];
  if (all.length >= DIFF_FILE_CAP) {
    return {
      ok: false,
      reason: "diff-incomplete",
      detail: `the diff has ${DIFF_FILE_CAP} or more files, GitHub's compare limit; read the files you need with read_repo_file at head instead`,
    };
  }
  const wanted = options.paths === undefined ? undefined : new Set(options.paths);
  const files: DiffFile[] = [];
  const omittedPaths: string[] = [];
  let budget = LIMITS.diffChars;

  for (const file of all) {
    // A rename is selected by either of its paths, and its paths are scrubbed before they leave this module:
    // a PR can name a file with a credential-shaped value, and the result goes to a model and to a public review.
    const path = redactSecrets(file.filename).text;
    const previous = file.previous_filename === undefined ? undefined : redactSecrets(file.previous_filename).text;
    if (wanted !== undefined && !wanted.has(file.filename) && (file.previous_filename === undefined || !wanted.has(file.previous_filename))) {
      continue;
    }
    const entry: DiffFile = {
      path,
      status: file.status,
      additions: file.additions,
      deletions: file.deletions,
    };
    if (previous !== undefined) {
      entry.previousPath = previous;
    }
    if (file.patch === undefined) {
      entry.patchOmitted = "GitHub gave no patch: the file is binary or too large to diff";
    } else {
      // The budget is spent on what is returned, so it is charged the redacted text's length, which can be longer.
      const text = redactSecrets(file.patch).text;
      if (text.length > budget) {
        entry.patchOmitted = `over the remaining size budget (${text.length} chars); read the file at head instead`;
        omittedPaths.push(path);
      } else {
        entry.patch = text;
        budget -= text.length;
      }
    }
    files.push(entry);
  }

  return {
    ok: true,
    totalFiles: all.length,
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

const KEY_BEGIN = /-----BEGIN [A-Z ]*PRIVATE KEY-----/;
const KEY_END = /-----END [A-Z ]*PRIVATE KEY-----/;

/**
 * Every line of a private key block, for the whole file, with the line count kept.
 *
 * The scrubber needs the BEGIN line to know a block is a key, so a window that starts inside
 * the body saw only base64. Blocks are replaced here, before the window is cut, one line for
 * each line. A block with no END line runs to the end of the file, as the scrubber does. A
 * key that begins and ends on one line is left for the scrubber, which handles it there.
 */
function redactKeyBlockLines(lines: readonly string[]): string[] {
  let inBlock = false;
  return lines.map((line) => {
    if (inBlock) {
      if (KEY_END.test(line)) {
        inBlock = false;
      }
      return REDACTED_KEY_LINE;
    }
    if (!KEY_BEGIN.test(line) || KEY_END.test(line)) {
      return line;
    }
    inBlock = !KEY_END.test(line);
    return REDACTED_KEY_LINE;
  });
}

const REDACTED_KEY_LINE = "<redacted:private-key>";

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
  const scrubbed = redactSecrets(redactKeyBlockLines(lines).slice(startLine - 1, endLine).join("\n")).text;
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

/** The first `listEntries` paths, and whether the listing was cut to fit. */
export function capListing(paths: readonly string[]): { paths: string[]; truncated: boolean } {
  return { paths: paths.slice(0, LIMITS.listEntries), truncated: paths.length > LIMITS.listEntries };
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
  const capped = capListing(matching);
  return { sha, paths: capped.paths, truncated: Boolean(data.truncated) || capped.truncated };
}
