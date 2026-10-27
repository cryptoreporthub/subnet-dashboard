/**
 * Flake-aware base-vs-head pytest comparison over JUnit XML, plus the
 * docs-only carry-over rule. Pure: strings in, structured verdict out.
 * Both XML inputs come from the runner (see `lib/runner.ts`), never from the
 * model, and the flake list comes from a committed file (see `lib/flakes.ts`).
 * The two rules that keep a comparison honest:
 *
 * - **Zero testcases is a failure, not a pass.** An empty or truncated report
 *   parses to "no failures", which would read as `clean`. A suite that collected
 *   nothing proves nothing, so it is `zero-testcases` and blocks the gate.
 * - **Carry-over is deny-by-default.** A new head may reuse a clean result only
 *   when every changed file is on an explicit non-code allowlist. Anything not
 *   on that list — `.html`, `.yml`, `.js`, `Dockerfile`, a `.json` fixture, an
 *   extension we have never seen — counts as code and forces a real run.
 */

import type { SuiteState } from "./gate.js";

export type JunitCase = {
  classname: string;
  name: string;
  /** Stable identity: `classname::name`. */
  id: string;
  outcome: "passed" | "failed" | "error" | "skipped";
  /** Failure text, when the runner gave one. */
  detail?: string;
};

export type SuiteDiff = {
  /** Failures that are new at head: the regressions. */
  newFailures: string[];
  /** Failures present at base that no longer fail at head. */
  fixed: string[];
  /** Failures that flipped between base and head but are on the known-flake list. */
  flakyRetriedOk: string[];
  /** Failures present at both base and head: pre-existing, not caused here. */
  preExisting: string[];
  clean: boolean;
  /**
   * Why a comparison cannot be trusted at all. Present means `clean` is false
   * no matter what the failure lists say.
   */
  invalid?: "zero-testcases";
  /** Testcase counts, so a reader can see the report was real. */
  counts: { base: number; head: number };
};

function decodeEntities(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function attr(attrs: string, name: string): string | undefined {
  const match = new RegExp(`\\b${name}\\s*=\\s*"([^"]*)"`).exec(attrs);
  return match?.[1] === undefined ? undefined : decodeEntities(match[1]);
}

/**
 * Parse the `<testcase>` elements of a JUnit XML report.
 *
 * A deliberately small reader: JUnit is the one format the cloud runner emits,
 * and a full XML parser would be a dependency for three tags. Nested
 * `<failure>` / `<error>` / `<skipped>` children decide the outcome.
 */
export function parseJunit(xml: string): JunitCase[] {
  const cases: JunitCase[] = [];
  const testcase = /<testcase\b([^>]*?)(\/>|>([\s\S]*?)<\/testcase>)/g;
  let match: RegExpExecArray | null = testcase.exec(xml);
  while (match !== null) {
    const attrs = match[1] ?? "";
    const body = match[3] ?? "";
    const classname = attr(attrs, "classname") ?? "";
    const name = attr(attrs, "name") ?? "";
    if (name !== "") {
      let outcome: JunitCase["outcome"] = "passed";
      let detail: string | undefined;
      const failure = /<(failure|error)\b([^>]*)>([\s\S]*?)<\/\1>/.exec(body);
      if (failure !== null) {
        outcome = failure[1] === "error" ? "error" : "failed";
        const message = attr(failure[2] ?? "", "message");
        detail = (message ?? decodeEntities((failure[3] ?? "").trim())).slice(0, 500);
      } else if (/<skipped\b/.test(body)) {
        outcome = "skipped";
      }
      cases.push({ classname, name, id: `${classname}::${name}`, outcome, detail });
    }
    match = testcase.exec(xml);
  }
  return cases;
}

function failing(cases: readonly JunitCase[]): Map<string, JunitCase> {
  const map = new Map<string, JunitCase>();
  for (const c of cases) {
    if (c.outcome === "failed" || c.outcome === "error") {
      map.set(c.id, c);
    }
  }
  return map;
}

export type DiffInput = {
  baseXml: string;
  headXml: string;
  /** Known-flaky test ids, `classname::name`. */
  knownFlakes?: readonly string[];
};

export function diffJunit(input: DiffInput): SuiteDiff {
  const baseCases = parseJunit(input.baseXml);
  const headCases = parseJunit(input.headXml);
  const counts = { base: baseCases.length, head: headCases.length };

  if (counts.head === 0) {
    // A report with no testcases cannot show a regression, and it cannot show
    // the absence of one either. Treat it as a failed run.
    return {
      newFailures: [],
      fixed: [],
      flakyRetriedOk: [],
      preExisting: [],
      clean: false,
      invalid: "zero-testcases",
      counts,
    };
  }

  const base = failing(baseCases);
  const head = failing(headCases);
  const flakes = new Set(input.knownFlakes ?? []);

  const newFailures: string[] = [];
  const preExisting: string[] = [];
  const flakyRetriedOk: string[] = [];

  for (const id of head.keys()) {
    if (base.has(id)) {
      preExisting.push(id);
    } else if (flakes.has(id)) {
      // On the known-flake list and absent at base: a flip, not a regression.
      flakyRetriedOk.push(id);
    } else {
      newFailures.push(id);
    }
  }

  const fixed: string[] = [];
  for (const id of base.keys()) {
    if (!head.has(id)) {
      fixed.push(id);
    }
  }

  return {
    newFailures: newFailures.sort(),
    fixed: fixed.sort(),
    flakyRetriedOk: flakyRetriedOk.sort(),
    preExisting: preExisting.sort(),
    clean: newFailures.length === 0,
    counts,
  };
}

/**
 * Paths that provably cannot change a pytest outcome: prose and images.
 *
 * Everything else is code for this purpose. That direction is deliberate — the
 * cost of a false "code" is one suite run, and the cost of a false "prose" is a
 * head that ships unverified. Notably absent on purpose: `.yml` (workflows run
 * the tests), `.html` (a Jinja template is asserted on by
 * `test_hold_shadows.py`), `.js`, `.json`, `.sh`, and files with no extension
 * (`Dockerfile`, `Procfile`, `LICENSE`).
 */
const NON_CODE: readonly RegExp[] = [/\.mdx?$/i, /\.(?:png|jpe?g|gif|svg|webp|ico)$/i];

/** Changed files that block a suite carry-over: every file not proven non-code. */
export function carryBlockingFiles(changedFiles: readonly string[]): string[] {
  return changedFiles.filter((file) => !NON_CODE.some((pattern) => pattern.test(file)));
}

/**
 * May this head reuse an earlier head's clean suite result?
 *
 * Two independent conditions, and both must hold:
 *
 * 1. **Nothing a suite can observe changed.** Deny-by-default: only the prose
 *    and image allowlist may carry.
 * 2. **The source SHA has a recorded `clean` result.** `carryFromSha` used to be
 *    any SHA the caller named, never checked against a real run — so a model
 *    could carry from a head that had never been tested, or had failed.
 */
export function carryDecision(input: {
  changedFiles: readonly string[];
  /** The suite state recorded at `carryFromSha`, or "missing". */
  recordedAtCarryFrom: SuiteState;
}): { ok: true } | { ok: false; reason: "code-changed" | "no-clean-source"; blocking?: string[] } {
  const blocking = carryBlockingFiles(input.changedFiles);
  if (blocking.length > 0) {
    return { ok: false, reason: "code-changed", blocking };
  }
  if (input.recordedAtCarryFrom !== "clean") {
    return { ok: false, reason: "no-clean-source" };
  }
  return { ok: true };
}
