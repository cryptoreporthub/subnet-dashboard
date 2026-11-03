/**
 * Build a reviewer-facing list of guard conditions removed or relaxed in a unified diff.
 *
 * Rules (generic — not tuned to any eval fixture):
 * 1. **Removed**: a deleted line (`-` hunk line) whose body looks like a guard
 *    (`if`/`elif`/`while`/`assert`/`raise`/`except`, or `return`/`require(`/`guard(`).
 * 2. **Relaxed**: a `-`/`+` pair in the same hunk where both bodies look like guards and the
 *    removed condition stem strictly extends the added stem (same prefix, more conjuncts).
 */

export type GuardChange = {
  path: string;
  kind: "removed" | "relaxed";
  /** One-line summary without diff prefixes. */
  line: string;
};

const GUARDish =
  /^\s*(?:if\b|elif\b|while\b|assert\b|raise\b|except\b|guard\b|require\s*\(|return\s+if\b)/i;

function stripDiffPrefix(raw: string): string | undefined {
  if (raw.startsWith("---") || raw.startsWith("+++") || raw.startsWith("@@")) {
    return undefined;
  }
  if (raw.startsWith("-")) {
    return raw.slice(1);
  }
  if (raw.startsWith("+")) {
    return raw.slice(1);
  }
  return undefined;
}

function looksLikeGuard(body: string): boolean {
  const t = body.trim();
  return t.length > 0 && GUARDish.test(t);
}

function conditionStem(line: string): string {
  return line.trim().replace(/:\s*$/, "");
}

function isStrictlyWeaker(removed: string, added: string): boolean {
  const r = conditionStem(removed);
  const a = conditionStem(added);
  if (r === a || r.length <= a.length) {
    return false;
  }
  return r.startsWith(a);
}

/** Scan one file patch; `patch` may be undefined (returns []). */
export function guardsRemovedOrRelaxedInPatch(path: string, patch: string | undefined): GuardChange[] {
  if (patch === undefined || patch.length === 0) {
    return [];
  }
  const lines = patch.split("\n");
  const out: GuardChange[] = [];
  for (let i = 0; i < lines.length; i++) {
    const removed = stripDiffPrefix(lines[i] ?? "");
    if (removed === undefined || !lines[i]!.startsWith("-")) {
      continue;
    }
    if (looksLikeGuard(removed)) {
      const next = stripDiffPrefix(lines[i + 1] ?? "");
      if (next !== undefined && lines[i + 1]!.startsWith("+") && looksLikeGuard(next) && isStrictlyWeaker(removed, next)) {
        out.push({ path, kind: "relaxed", line: removed.trim() });
        i += 1;
        continue;
      }
      out.push({ path, kind: "removed", line: removed.trim() });
    }
  }
  return out;
}

export function guardsRemovedOrRelaxedSection(changes: GuardChange[]): string {
  if (changes.length === 0) {
    return "";
  }
  const body = changes
    .map((c) => `- \`${c.path}\` (${c.kind}): ${c.line}`)
    .join("\n");
  return `## Guards removed or relaxed (from diff)\n\n${body}\n\nA PASS must explain each line above or post MODIFY/FAIL.`;
}

export function attachGuardsSection<T extends { files: { path: string; patch?: string }[] }>(
  diff: T,
): T & { guardsRemovedOrRelaxed: string } {
  const changes = diff.files.flatMap((f) => guardsRemovedOrRelaxedInPatch(f.path, f.patch));
  return { ...diff, guardsRemovedOrRelaxed: guardsRemovedOrRelaxedSection(changes) };
}
