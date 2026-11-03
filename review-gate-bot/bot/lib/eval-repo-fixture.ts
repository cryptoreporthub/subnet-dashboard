import type { PrSnapshot } from "./gh.js";
import type { RepoFixture } from "./fixtures.js";

/** Paths the fixture PR diff touches (`pr.json` → `files`). */
export function evalPrChangedPaths(pr: PrSnapshot): ReadonlySet<string> {
  return new Set(pr.files);
}

/**
 * Eval harness: file text at the PR base commit.
 *
 * - Changed file: `baseFiles[path]` when present.
 * - PR-added/changed path with no base snapshot: absent (does not exist at base).
 * - Unchanged context: `files[path]` (identical at base and head in production).
 */
export function evalRepoTextAtBase(
  repo: RepoFixture,
  path: string,
  changed: ReadonlySet<string>,
): string | undefined {
  const baseFiles = repo.baseFiles ?? {};
  if (Object.prototype.hasOwnProperty.call(baseFiles, path)) {
    return baseFiles[path];
  }
  if (changed.has(path)) {
    return undefined;
  }
  return repo.files[path];
}

/** Paths that exist at base for eval listing (baseFiles + unchanged head context; no PR-added-only paths). */
export function evalRepoPathsAtBase(repo: RepoFixture, changed: ReadonlySet<string>): string[] {
  const baseFiles = repo.baseFiles ?? {};
  const paths = new Set<string>(Object.keys(baseFiles));
  for (const path of Object.keys(repo.files)) {
    if (!changed.has(path)) {
      paths.add(path);
    }
  }
  return [...paths];
}
