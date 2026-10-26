/**
 * Flake-aware base-vs-head pytest comparison over JUnit XML, plus the
 * docs-only carry-over rule. Pure: strings in, structured verdict out.
 */

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
  newFailures: string[];
  /** Failures present at base that no longer fail at head. */
  fixed: string[];
  /** Failures that flipped between base and head but are on the known-flake list. */
  flakyRetriedOk: string[];
  /** Failures present at both base and head: pre-existing, not caused here. */
  preExisting: string[];
  clean: boolean;
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
  const base = failing(parseJunit(input.baseXml));
  const head = failing(parseJunit(input.headXml));
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
  };
}

/** Paths that can reach pytest. A change to any of these means no carry-over. */
const PYTEST_REACHABLE: readonly RegExp[] = [
  /\.py$/i,
  // A shell script can invoke pytest or mutate state a fixture reads. PR 1519's
  // one-line `echo` edit to a `.sh` is exactly this case.
  /\.sh$/i,
  /(^|\/)conftest\.py$/i,
  /(^|\/)pytest\.ini$/i,
  /(^|\/)tox\.ini$/i,
  /(^|\/)setup\.cfg$/i,
  /(^|\/)pyproject\.toml$/i,
  /(^|\/)requirements[^/]*\.txt$/i,
  /(^|\/)constraints[^/]*\.txt$/i,
  /(^|\/)\.coveragerc$/i,
  /(^|\/)data\/.*\.json$/i,
  /(^|\/)config\/.*\.json$/i,
];

/**
 * Changed files that can change a pytest outcome.
 *
 * Carrying a suite result is only sound when nothing the suite can observe
 * changed. `.md` and other prose never reach pytest; a `.sh` script or a JSON
 * data file can, through a subprocess or a fixture, so both count as reachable.
 * Conservative by design: a false "reachable" costs a suite run, a false
 * "unreachable" ships an unverified head.
 */
export function pytestReachable(changedFiles: readonly string[]): string[] {
  return changedFiles.filter((file) => PYTEST_REACHABLE.some((pattern) => pattern.test(file)));
}
