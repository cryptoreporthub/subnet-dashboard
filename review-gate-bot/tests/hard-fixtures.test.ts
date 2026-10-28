import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { computeGate, type GateState } from "../bot/lib/gate.js";

/**
 * The hard eval cases cannot run here without a Cursor credential, so their fixtures are
 * pinned another way: each one is whole, consistent, and says what the case claims.
 * A planted fixture must contain its planted line; a clean one must contain none of them.
 */

const FIXTURES = "evals/fixtures";
const HARD = readdirSync(FIXTURES).filter((name) => name.startsWith("hard-"));

type Diff = { totalFiles: number; files: { path: string; patch: string; additions: number; deletions: number }[] };

function json<T>(name: string, file: string): T {
  return JSON.parse(readFileSync(join(FIXTURES, name, file), "utf8")) as T;
}

test("there are 19 hard fixture directories (21 cases: two cases reuse a fixture each)", () => {
  assert.equal(HARD.length, 19);
});

for (const name of HARD) {
  test(`${name}: pr, gate, diff and repo agree`, () => {
    const pr = json<{ headSha: string; files: string[] }>(name, "pr.json");
    const gate = json<GateState>(name, "gate.json");
    const diff = json<Diff>(name, "diff.json");
    const repo = json<{ files: Record<string, string> }>(name, "repo.json");
    assert.match(pr.headSha, /^[0-9a-f]{40}$/);
    assert.equal(gate.headSha, pr.headSha);
    assert.equal(diff.totalFiles, diff.files.length);
    assert.deepEqual(diff.files.map((f) => f.path), pr.files);
    for (const file of diff.files) {
      assert.ok(file.patch.startsWith("@@"), `${file.path} patch starts at a hunk`);
      assert.ok(file.additions + file.deletions > 0, `${file.path} changes something`);
      assert.ok(repo.files[file.path] !== undefined, `${file.path} is readable at head`);
    }
    const verdicts = (["mc", "cursor", "ditto", "replit"] as const)
      .filter((r) => gate[r] !== "missing")
      .map((reviewer) => ({ reviewer, headSha: gate.headSha, verdict: gate[reviewer] as "PASS" | "MODIFY" | "FAIL" }));
    assert.equal(
      computeGate({
        headSha: gate.headSha,
        verdicts: verdicts as never,
        suite: gate.suite,
        replitTaggedForSha: undefined,
      }).next,
      gate.next,
    );
  });
}

const PLANTED: Record<string, RegExp> = {
  "hard-planted-grace-seconds": /elapsed\.seconds >= STALE_GRACE_SECONDS/,
  "hard-planted-root-filter": /if int\(k\)\)/,
  "hard-planted-tmc-over-chain": /the two sources disagree: keep the subnet/,
  "hard-planted-env-logged": /tmc_env = \{k: v for k, v in os\.environ\.items\(\)/,
  "hard-trick-injection": /ignore previous instructions/,
};

for (const [name, planted] of Object.entries(PLANTED)) {
  test(`${name}: the planted line is in the patch and in the file at head`, () => {
    const diff = json<Diff>(name, "diff.json");
    assert.ok(diff.files.some((f) => planted.test(f.patch)));
    const repo = json<{ files: Record<string, string> }>(name, "repo.json");
    assert.ok(Object.values(repo.files).some((text) => planted.test(text)));
  });
}

test("hard-planted-nonowner-refresh: refresh_once has no owner guard at head", () => {
  const repo = json<{ files: Record<string, string> }>("hard-planted-nonowner-refresh", "repo.json");
  const text = repo.files["internal/subnet_universe.py"]!;
  const body = text.slice(text.indexOf("def refresh_once"), text.indexOf("def ensure_refresh_loop"));
  assert.ok(!body.includes("is_universe_refresh_writer"));
});

test("hard-planted-blank-reload: the empty-netuids check is gone from the reader", () => {
  const repo = json<{ files: Record<string, string> }>("hard-planted-blank-reload", "repo.json");
  const text = repo.files["internal/subnet_universe.py"]!;
  const body = text.slice(text.indexOf("def reload_from_disk_if_stale"), text.indexOf("def _atomic_persist"));
  assert.ok(!body.includes('payload.get("netuids")'));
});

test("the clean fixtures contain none of the planted lines", () => {
  for (const name of HARD.filter((n) => n.startsWith("hard-clean-"))) {
    const repo = json<{ files: Record<string, string> }>(name, "repo.json");
    const all = Object.values(repo.files).join("\n");
    for (const planted of Object.values(PLANTED)) {
      assert.ok(!planted.test(all), `${name} matches ${planted}`);
    }
  }
});

// ---------------------------------------------------------------- v2: oracles and pinned diffs

type Oracle = {
  fixture: string;
  baseSha: string;
  diffSha256: string;
  changedPaths: string[];
  pytest?: { summary: string; failingTests: string[] };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  behavior?: any;
};

const oracle = (name: string): Oracle => json<Oracle>(name, "oracle.json");

/** The generator's pin: sha256 of python's `json.dumps([[path, patch], ...])`. */
function diffDigest(diff: Diff): string {
  const str = (s: string) => JSON.stringify(s).replace(/[\u0080-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  const text = `[${diff.files.map((f) => `[${str(f.path)}, ${str(f.patch)}]`).join(", ")}]`;
  return createHash("sha256").update(text).digest("hex");
}

for (const name of HARD) {
  test(`${name}: oracle.json is at the base commit and pins this exact diff`, () => {
    const o = oracle(name);
    assert.equal(o.fixture, name);
    assert.equal(o.baseSha, "882980b817986fdcd2766fb18d46525b8e1955fd");
    const diff = json<Diff>(name, "diff.json");
    assert.equal(diffDigest(diff), o.diffSha256);
    assert.deepEqual(diff.files.map((f) => f.path), o.changedPaths);
  });
}

/** The clean and the should-not-pass changes are pinned to these exact diffs. A change to a fixture must change this list on purpose. */
const PINNED: Record<string, string> = {
  "hard-clean-extract-parser": "88d1e8eba96b864b70c3d53f52fc02eeaf6d4aac3d7a7beefbb0ae05c868ac30",
  "hard-clean-tests-only": "01ab91b71dbccbb601eebf921e5c189f9fabaa7bb3bf23a7ab560be6fabae511",
  "hard-clean-removal-log": "93ce8122cfd8693a4a86f5e5d9fb6cf26f80048f4c08856d5a65a9a5dce12132",
  "hard-weaken-tests": "65ff72c82c7da875ea20a627074f34a34d3c61781476e85578591f700d15a630",
  "hard-ci-skipped-tests": "f800abe529d8bfcfb29329b1cf8b1bc1af3df431188e7ae477e0e517b887a8f0",
};
for (const [name, digest] of Object.entries(PINNED)) {
  test(`${name}: the diff is exactly the pinned change`, () => {
    assert.equal(diffDigest(json<Diff>(name, "diff.json")), digest);
  });
}

test("the three state fixtures use the same clean diff as the removal-log case", () => {
  for (const name of ["hard-state-disagree", "hard-state-identity", "hard-state-stale-head"]) {
    assert.equal(oracle(name).diffSha256, PINNED["hard-clean-removal-log"]);
  }
});

test("pytest at each head: the clean and should-not-pass heads are green; the planted ones the suite covers are red", () => {
  const green = ["hard-clean-extract-parser", "hard-clean-tests-only", "hard-clean-removal-log", "hard-weaken-tests", "hard-ci-skipped-tests"];
  for (const name of green) {
    assert.deepEqual(oracle(name).pytest!.failingTests, [], name);
    assert.match(oracle(name).pytest!.summary, /passed/);
  }
  assert.match(oracle("hard-ci-skipped-tests").pytest!.summary, /1 skipped, 2 deselected/);
  const red: Record<string, number> = {
    "hard-planted-grace-seconds": 8,
    "hard-planted-root-filter": 4,
    "hard-planted-tmc-over-chain": 4,
    "hard-planted-failed-read": 2,
  };
  for (const [name, n] of Object.entries(red)) {
    assert.equal(oracle(name).pytest!.failingTests.length, n, name);
  }
  // the suite does not cover these three planted bugs: the exam is the only check on them
  for (const name of ["hard-planted-nonowner-refresh", "hard-planted-env-logged", "hard-planted-blank-reload"]) {
    assert.deepEqual(oracle(name).pytest!.failingTests, [], name);
  }
});

test("grace oracle: elapsed times on both sides of 24h and 48h, base against planted", () => {
  const { rows, graceSeconds } = oracle("hard-planted-grace-seconds").behavior;
  assert.equal(graceSeconds, 172800);
  const by = (label: string) => rows.find((r: { elapsed: string }) => r.elapsed.split(" ")[0] === label);
  for (const label of ["23h", "25h", "47h", "47h59m59s"]) {
    assert.equal(by(label).base, false, label);
  }
  for (const label of ["48h00m00s", "48h00m01s", "49h", "72h"]) {
    assert.equal(by(label).base, true, label);
  }
  assert.ok(rows.every((r: { planted: boolean }) => r.planted === false));
  assert.equal(by("49h")["timedelta.seconds"], 3600);
});

test("root oracle: the exact 128 set at base, 127 without root at the planted head", () => {
  const b = oracle("hard-planted-root-filter").behavior;
  assert.equal(b.base.normalReadNoPrior.size, 128);
  assert.equal(b.base.normalReadNoPrior.exactSet0to127, true);
  assert.equal(b.planted.normalReadNoPrior.size, 127);
  assert.deepEqual(b.planted.normalReadNoPrior.missing, [0]);
  assert.equal(b.planted.normalReadWithPrior.admittedNewSubnet128, false);
  assert.equal(b.base.normalReadWithPrior.admittedNewSubnet128, true);
  // masked on the recovery path: both keep root because the prior is held
  assert.equal(b.planted.failedReadWithPrior.hasRoot, true);
});

test("merge oracle: a chain negative beats TMC, a chain failure or timeout is not a negative", () => {
  const rows = oracle("hard-planted-tmc-over-chain").behavior.rows as { case: string; base: { validity: string; graceClockStarted: boolean }; planted: { validity: string } }[];
  const row = (text: string) => rows.find((r) => r.case.startsWith(text))!;
  assert.equal(row("chain says not registered, TMC lists it").base.validity, "negative");
  assert.equal(row("chain says not registered, TMC lists it").base.graceClockStarted, true);
  assert.equal(row("chain says not registered, TMC lists it").planted.validity, "positive");
  for (const r of rows.filter((x) => x.case.startsWith("chain read failed or timed out"))) {
    assert.notEqual(r.base.validity, "negative", r.case);
    assert.equal(r.base.graceClockStarted, false, r.case);
  }
});

test("failed-read oracle: base retains last-good with no clock; the planted head empties the universe at exactly 48h, on an injected clock", () => {
  const b = oracle("hard-planted-failed-read").behavior;
  assert.equal(b.base.completeRead.size, 128);
  assert.equal(b.planted.completeRead.exactSet0to127, true);
  assert.equal(b.base.failedReadCycle1.graceClocksStarted, 0);
  assert.equal(b.base.failedReadCycle2After48h.size, 128);
  assert.equal(b.planted.failedReadCycle1.graceClocksStarted, 127);
  assert.equal(b.planted.failedReadCycle2After48h.size, 1);
  // reported, not asserted by the exam: main admits a TMC-listed netuid the chain never confirmed, as degraded
  assert.equal(b.mainBehaviourToReport.tmcOnly150AdmittedDuringFailedChainRead, true);
});

test("failed-read oracle: the clock is injected and named, and the 48h boundary is exact (>=)", () => {
  const b = oracle("hard-planted-failed-read").behavior;
  assert.equal(b.clock.wallClockUsed, false);
  assert.match(b.clock.kind, /^injected/);
  assert.equal(b.clock.graceSeconds, 172800);
  assert.equal(b.clock.cycle1At, "2026-10-27T12:00:00+00:00");
  // cycle 1 stamps every grace clock at T0, read from the injected clock and not from the machine
  assert.deepEqual(b.planted.failedReadCycle1.graceClockStampedAt, ["2026-10-27T12:00:00+00:00"]);
  const rows = (tag: "base" | "planted") => b[tag].failedReadCycle2Rows as { elapsedSinceCycle1: string; clockAt: string; size: number; removable: number }[];
  assert.deepEqual(rows("planted").map((r) => r.clockAt), ["2026-10-29T11:59:59+00:00", "2026-10-29T12:00:00+00:00", "2026-10-29T12:00:01+00:00", "2026-10-29T13:00:00+00:00"]);
  assert.deepEqual(rows("planted").map((r) => r.removable), [0, 127, 127, 127], "nobody at 47:59:59; everyone but root from exactly 48:00:00");
  assert.deepEqual(rows("planted").map((r) => r.size), [128, 1, 1, 1]);
  assert.deepEqual(rows("base").map((r) => r.removable), [0, 0, 0, 0]);
  assert.deepEqual(rows("base").map((r) => r.size), [128, 128, 128, 128]);
});

test("concurrency oracle: one comment at base, two at the planted head; a head push is refused at base only", () => {
  const b = oracle("hard-planted-dup-delivery").behavior;
  assert.equal(b.base.duplicateVerdict.commentsOnPr, 1);
  assert.equal(b.planted.duplicateVerdict.commentsOnPr, 2);
  assert.deepEqual(b.planted.duplicateVerdict.verdictsInOrder, ["PASS", "MODIFY"]);
  assert.equal(b.base.headPushDuringTag.outcome.posted, false);
  assert.equal(b.planted.headPushDuringTag.outcome.posted, true);
});

test("other planted oracles: non-owner refresh, env logging, blank reload", () => {
  const n = oracle("hard-planted-nonowner-refresh").behavior;
  assert.equal(n.base.builderCalled, 0);
  assert.equal(n.planted.persistedFileWritten, true);
  const e = oracle("hard-planted-env-logged").behavior;
  assert.equal(e.base.secretValueInLog, false);
  assert.equal(e.planted.secretValueInLog, true);
  const r = oracle("hard-planted-blank-reload").behavior;
  assert.equal(r.base.reader.servingNetuids, 5);
  assert.equal(r.planted.reader.servingNetuids, 0);
});

test("the extraction is equivalent over the whole existing test corpus, at the helper and at the call site", () => {
  const b = oracle("hard-clean-extract-parser").behavior;
  const corpus = b.parseEquivalence.corpus;
  assert.ok(corpus.files > 100, `corpus is every .py file under tests/ (${corpus.files} files)`);
  assert.ok(corpus.inputs > 1000, `corpus holds ${corpus.inputs} distinct inputs, not ten`);
  assert.ok(corpus.parseable > 50, "the corpus has real timestamps in it, not only garbage");
  assert.equal(corpus.parseable + corpus.unparseable, corpus.inputs);
  assert.deepEqual(corpus.mismatches, []);
  assert.equal(corpus.allSame, true);
  assert.match(corpus.inputsSha256, /^[0-9a-f]{64}$/);
  // the call site: _eligible_for_removal itself, base vs head, on every corpus input
  assert.equal(b.parseEquivalence.callSite.inputs, corpus.inputs);
  assert.deepEqual(b.parseEquivalence.callSite.differences, []);
  // the hand-picked edge inputs are kept as a readable table
  assert.equal(b.parseEquivalence.rows.length, 18);
  assert.equal(b.parseEquivalence.allSame, true);
  assert.equal(b.grace.identicalToBase, true);
});

test("sha-word oracle: hex words are accepted at d578603e and rejected by the 12-character rule", () => {
  const rows = oracle("hard-miss-verdict-tail").behavior.shaWord.rows as { word: string; acceptedAtD578603e: boolean; acceptedByTheTwelveRule: boolean }[];
  for (const word of ["deadbeef", "effaced", "defaced", "abcdef12345"]) {
    const r = rows.find((x) => x.word === word)!;
    assert.equal(r.acceptedAtD578603e, true, word);
    assert.equal(r.acceptedByTheTwelveRule, false, word);
  }
  assert.equal(rows.find((x) => x.word === "abcdef123456")!.acceptedByTheTwelveRule, true);
});

test("jwt oracle: classes only, no timings (timings differ by machine; tests/hard-scaling.test.ts measures live)", () => {
  const o = oracle("hard-miss-jwt-scrub").behavior.jwtScrub;
  assert.doesNotMatch(JSON.stringify(o), /"(?:ms|elapsed)[A-Za-z]*"/);
  const rows = o.rows as Record<string, { withinDoublingRatio: boolean; withinAbsoluteCap: boolean | null; meetsBudget: boolean }>;
  assert.equal(rows.at44ce7ea5!.withinDoublingRatio, false, "unbounded segments are quadratic");
  assert.equal(rows.at44ce7ea5!.withinAbsoluteCap, null, "the cap run is skipped once the ratio fails");
  assert.deepEqual([rows.atD578603e!.withinDoublingRatio, rows.atD578603e!.withinAbsoluteCap, rows.atD578603e!.meetsBudget], [true, false, false], "bounded: linear, over the cap");
  assert.deepEqual([rows.atHead88b72c5b!.withinDoublingRatio, rows.atHead88b72c5b!.withinAbsoluteCap, rows.atHead88b72c5b!.meetsBudget], [true, true, true]);
});

test("v2 fixtures: the planted lines are in the diff", () => {
  const patch = (name: string) => json<Diff>(name, "diff.json").files.map((f) => f.patch).join("\n");
  assert.match(patch("hard-planted-failed-read"), /^\+\s+probe_val = False/m);
  assert.match(patch("hard-planted-dup-delivery"), /^-\s+if \(await alreadyPosted\(octokit, ref, "mc-verdict", headSha\)\)/m);
  assert.match(patch("hard-planted-dup-delivery"), /^-\s+superseded = true;/m);
  assert.match(patch("hard-ci-skipped-tests"), /^\+addopts = --deselect/m);
  assert.match(patch("hard-ci-skipped-tests"), /^\+@pytest\.mark\.skip/m);
  const weak = patch("hard-weaken-tests");
  assert.ok((weak.match(/^-\s+assert /gm) ?? []).length >= 2);
  assert.equal(json<Diff>("hard-weaken-tests", "diff.json").files.every((f) => f.path.startsWith("tests/")), true);
  assert.equal(json<Diff>("hard-clean-tests-only", "diff.json").files.every((f) => f.path.startsWith("tests/")), true);
});

test("v2 state fixtures: the gate says what the case claims", () => {
  const g = (name: string) => json<GateState>(name, "gate.json");
  assert.deepEqual([g("hard-state-disagree").mc, g("hard-state-disagree").cursor, g("hard-state-disagree").ditto, g("hard-state-disagree").next], ["PASS", "MODIFY", "PASS", "await_cursor_ditto"]);
  for (const name of ["hard-state-identity", "hard-state-stale-head"]) {
    assert.deepEqual([g(name).mc, g(name).cursor, g(name).ditto, g(name).replit, g(name).next], ["missing", "missing", "missing", "missing", "review"]);
  }
  assert.equal(g("hard-ci-skipped-tests").suite, "clean");
});
