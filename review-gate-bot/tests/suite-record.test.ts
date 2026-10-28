import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { recordSuiteComparison, runSuiteIfDue } from "../bot/lib/suite-record.js";
import { readSuiteState } from "../bot/lib/gh.js";
import { JUNIT_ARTIFACT, type RunnerReader } from "../bot/lib/runner.js";
import { suiteKey } from "../bot/lib/gh.js";

const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const HEAD = "c".repeat(40);
const BASE = "b".repeat(40);
const CLEAN = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="a"/></testsuite></testsuites>';

/** A stored zip with one JUnit file, which is all the reader needs. */
function zipOf(text: string): Uint8Array {
  const name = Buffer.from("pytest.xml");
  const data = Buffer.from(text, "utf8");
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt32LE(data.length, 18);
  local.writeUInt32LE(data.length, 22);
  local.writeUInt16LE(name.length, 26);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt32LE(data.length, 20);
  central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(name.length, 28);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(central.length + name.length, 12);
  end.writeUInt32LE(local.length + name.length + data.length, 16);
  return new Uint8Array(Buffer.concat([local, name, data, central, name, end]));
}

function fixture(changedFiles: string[]) {
  const downloads = { count: 0 };
  const reader: RunnerReader = {
    runsForSha: async () => [{ id: 77, conclusion: "success" }],
    artifactsForRun: async () => [{ id: 5, name: JUNIT_ARTIFACT }],
    artifactZip: async () => {
      downloads.count += 1;
      return zipOf(CLEAN);
    },
  };
  const store = new Map<string, unknown>();
  const kv = {
    get: async (key: string) => store.get(key),
    put: async (key: string, value: unknown) => void store.set(key, value),
    delete: async (key: string) => void store.delete(key),
  } as unknown as HostKvApi;
  const octokit = {
    rest: {
      repos: {
        compareCommitsWithBasehead: async () => ({ data: { files: changedFiles.map((filename) => ({ filename, status: "modified" })) } }),
      },
    },
  } as unknown as Octokit;
  return { reader, downloads, store, kv, octokit };
}

test("a PR that changes the suite's own definition is refused before any report is read", async () => {
  const f = fixture([".github/workflows/full-suite-junit.yml"]);
  const outcome = await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(outcome.ok, false);
  assert.equal(!outcome.ok && outcome.reason, "needs-joshua");
  assert.equal(f.downloads.count, 0, "no artifact is downloaded for a PR that rewrote how the suite runs");
  const recorded = f.store.get(suiteKey(REF, HEAD)) as { runId?: number; invalid?: string } | undefined;
  assert.equal(recorded?.runId, undefined, "no report was read, so no run is recorded");
  assert.equal(f.downloads.count, 0);
});

test("changing pytest.ini or a conftest anywhere in the tree is also refused", async () => {
  for (const file of ["pytest.ini", "tests/conftest.py", "pyproject.toml"]) {
    const f = fixture([file]);
    const outcome = await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
    assert.equal(!outcome.ok && outcome.reason, "needs-joshua", file);
  }
});

test("a PR that changes no suite-definition file is recorded as before", async () => {
  const f = fixture(["review-gate-bot/bot/lib/suite.ts"]);
  const outcome = await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(outcome.ok, true);
  assert.equal((f.store.get(suiteKey(REF, HEAD)) as { state?: string }).state, "clean");
});

test("renaming a suite-definition file away from its path is refused: the old path counts too", async () => {
  const f = fixture([]);
  const renamed = {
    rest: {
      repos: {
        compareCommitsWithBasehead: async () => ({
          data: { files: [{ filename: "tests/conftest_old.py", previous_filename: "tests/conftest.py", status: "renamed" }] },
        }),
      },
    },
  } as unknown as Octokit;
  const outcome = await recordSuiteComparison({ octokit: renamed, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(!outcome.ok && outcome.reason, "needs-joshua");
  assert.equal(f.downloads.count, 0);
});


test("a NEEDS-JOSHUA refusal is recorded with its reason and files, so the check can say why", async () => {
  const f = fixture(["pytest.ini"]);
  await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  const record = f.store.get(suiteKey(REF, HEAD)) as { state?: string; invalid?: string; detail?: string } | undefined;
  assert.equal(record?.state, "regressed", "not clean, and not left as an unrecorded wait");
  assert.equal(record?.invalid, "needs-joshua");
  assert.match(record?.detail ?? "", /pytest\.ini/);
});

test("a comparison with a base test missing at head records which tests are missing", async () => {
  const f = fixture([]);
  const reader: RunnerReader = {
    ...f.reader,
    artifactZip: async () => zipOf('<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="b"/></testsuite></testsuites>'),
  };
  const baseXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="a"/><testcase classname="tests.test_x" name="b"/></testsuite></testsuites>';
  let call = 0;
  const reader2: RunnerReader = {
    ...reader,
    artifactZip: async () => zipOf(++call === 1 ? '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="b"/></testsuite></testsuites>' : baseXml),
  };
  await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: reader2 });
  const record = f.store.get(suiteKey(REF, HEAD)) as { invalid?: string; missing?: string[] } | undefined;
  assert.equal(record?.invalid, "baseline-test-missing");
  assert.deepEqual(record?.missing, ["tests.test_x::a"]);
});

test("a missing baseline test reads as NEEDS-JOSHUA for the gate, not as a retryable regression", async () => {
  const f = fixture([]);
  let call = 0;
  const reader: RunnerReader = {
    ...f.reader,
    artifactZip: async () => zipOf(++call === 1 ? '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="b"/></testsuite></testsuites>' : '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="a"/><testcase classname="tests.test_x" name="b"/></testsuite></testsuites>'),
  };
  await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader });
  assert.equal(await readSuiteState(f.kv, REF, HEAD), "needs-joshua");
});


test("a suite-definition change is refused even when no run has finished, and later deliveries do not look up runs again", async () => {
  const f = fixture(["pytest.ini"]);
  let lookups = 0;
  const noRunYet: RunnerReader = {
    runsForSha: async () => {
      lookups += 1;
      return [];
    },
    artifactsForRun: async () => [],
    artifactZip: async () => new Uint8Array(),
  };
  const first = await runSuiteIfDue({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunYet });
  assert.equal(first, "refused:head-needs-joshua");
  const afterFirst = lookups;
  const second = await runSuiteIfDue({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunYet });
  assert.equal(second, "already-refused");
  assert.equal(lookups, afterFirst, "a refused head is not checked against the run list again");
  assert.equal(await readSuiteState(f.kv, REF, HEAD), "needs-joshua");
});

test("a long list of missing tests is summarised in the detail, and the full list stays in the record", async () => {
  const f = fixture([]);
  const many = (names: string[]) =>
    `<?xml version="1.0"?><testsuites><testsuite name="pytest">${names
      .map((n) => `<testcase classname="tests.test_x" name="${n}"/>`)
      .join("")}</testsuite></testsuites>`;
  const names = Array.from({ length: 3000 }, (_, i) => `test_${"x".repeat(150)}_${i}`);
  let call = 0;
  const reader: RunnerReader = {
    ...f.reader,
    artifactZip: async () => zipOf(++call === 1 ? many(["h"]) : many(names)),
  };
  await recordSuiteComparison({ octokit: f.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader });
  const record = f.store.get(suiteKey(REF, HEAD)) as { detail?: string; missing?: string[] } | undefined;
  assert.equal(record?.missing?.length, 3000, "the full list is kept");
  assert.ok((record?.detail ?? "").length <= 1000, `detail is ${record?.detail?.length} characters`);
  assert.match(record?.detail ?? "", /3000/);
});

/** A compare whose file list the test controls, and a count of how many times it was asked for. */
function compareOf(data: { files?: Array<{ filename: string; previous_filename?: string; status?: string }> }) {
  const calls = { count: 0 };
  const octokit = {
    rest: {
      repos: {
        compareCommitsWithBasehead: async () => {
          calls.count += 1;
          return { data };
        },
      },
    },
  } as unknown as Octokit;
  return { octokit, calls };
}

/** 300 changed files, the most GitHub's compare returns, none of them a suite-definition file. */
const CAPPED = Array.from({ length: 300 }, (_, i) => ({ filename: `app/module_${i}.py`, status: "modified" }));

function noRunReader(lookups: { count: number }): RunnerReader {
  return {
    runsForSha: async () => {
      lookups.count += 1;
      return [];
    },
    artifactsForRun: async () => [],
    artifactZip: async () => new Uint8Array(),
  };
}

test("a compare cut off at GitHub's file cap is refused as NEEDS-JOSHUA even when no run has finished", async () => {
  const f = fixture([]);
  const { octokit } = compareOf({ files: CAPPED });
  const lookups = { count: 0 };
  const outcome = await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunReader(lookups) });
  assert.equal(outcome, "refused:head-diff-incomplete", "not waiting:no-run, which would let a PR that never finishes its run pass");
  assert.equal(lookups.count, 0, "the refusal comes before any run is looked up");
  assert.equal(await readSuiteState(f.kv, REF, HEAD), "needs-joshua");
  const record = f.store.get(suiteKey(REF, HEAD)) as { invalid?: string; detail?: string } | undefined;
  assert.equal(record?.invalid, "needs-joshua");
  assert.match(record?.detail ?? "", /300 or more files/);
});

test("a compare with no file list at all is unknown and refused, not read as 'no suite files changed'", async () => {
  const f = fixture([]);
  const { octokit } = compareOf({});
  const lookups = { count: 0 };
  const outcome = await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunReader(lookups) });
  assert.equal(outcome, "refused:head-diff-incomplete");
  assert.equal(lookups.count, 0);
  assert.equal(await readSuiteState(f.kv, REF, HEAD), "needs-joshua");
});

test("a capped compare is final: the next delivery neither compares nor looks up a run again", async () => {
  const f = fixture([]);
  const { octokit, calls } = compareOf({ files: CAPPED });
  const lookups = { count: 0 };
  const reader = noRunReader(lookups);
  await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader });
  const afterFirst = calls.count;
  const second = await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader });
  assert.equal(second, "already-refused");
  assert.equal(calls.count, afterFirst);
  assert.equal(lookups.count, 0);
});

test("the compare_suite_runs path records a capped compare as NEEDS-JOSHUA too, so both paths record the same thing", async () => {
  const f = fixture([]);
  const { octokit } = compareOf({ files: CAPPED });
  const outcome = await recordSuiteComparison({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(!outcome.ok && outcome.reason, "needs-joshua");
  assert.equal(f.downloads.count, 0, "no report is read for a diff that cannot be checked whole");
  assert.equal(await readSuiteState(f.kv, REF, HEAD), "needs-joshua");
});

test("a compare just under the cap that changes no suite file still goes on to the run", async () => {
  const f = fixture([]);
  const { octokit } = compareOf({ files: CAPPED.slice(1) });
  const outcome = await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(outcome, "recorded");
});

test("a refusal for more than five suite-definition files keeps every path in the record, and the detail stays short", async () => {
  const paths = Array.from({ length: 12 }, (_, i) => `service_${i}/conftest.py`);
  const f = fixture([]);
  const { octokit } = compareOf({ files: [...paths.map((filename) => ({ filename, status: "modified" })), { filename: "app/x.py", status: "modified" }] });
  await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunReader({ count: 0 }) });
  const record = f.store.get(suiteKey(REF, HEAD)) as { invalid?: string; detail?: string; definitionFiles?: string[] } | undefined;
  assert.equal(record?.invalid, "needs-joshua");
  assert.deepEqual(record?.definitionFiles, paths, "all twelve paths can be inspected from the stored record");
  assert.match(record?.detail ?? "", /and 7 more/, "the check summary still shows only the first few");
});

test("the compare_suite_runs path keeps the full suite-definition list in the record too, with a rename's old path", async () => {
  const f = fixture([]);
  const { octokit } = compareOf({
    files: [
      { filename: "tests/conftest_new.py", previous_filename: "tests/conftest.py", status: "renamed" },
      { filename: "pytest.ini", status: "modified" },
      { filename: "a/conftest.py", status: "modified" },
      { filename: "b/conftest.py", status: "modified" },
      { filename: "c/conftest.py", status: "modified" },
      { filename: "d/conftest.py", status: "modified" },
    ],
  });
  await recordSuiteComparison({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  const record = f.store.get(suiteKey(REF, HEAD)) as { definitionFiles?: string[] } | undefined;
  assert.deepEqual(record?.definitionFiles, ["tests/conftest.py", "pytest.ini", "a/conftest.py", "b/conftest.py", "c/conftest.py", "d/conftest.py"]);
});

test("the widest refusal GitHub's compare allows stays bounded: every path kept, the detail short", async () => {
  const paths = Array.from({ length: 299 }, (_, i) => `pkg_${i}/${"d".repeat(60)}/conftest.py`);
  const f = fixture([]);
  const { octokit } = compareOf({ files: paths.map((filename) => ({ filename, status: "modified" })) });
  await runSuiteIfDue({ octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: noRunReader({ count: 0 }) });
  const record = f.store.get(suiteKey(REF, HEAD)) as { detail?: string; definitionFiles?: string[] } | undefined;
  assert.equal(record?.definitionFiles?.length, 299);
  assert.ok((record?.detail ?? "").length <= 1000, `detail is ${record?.detail?.length} characters`);
});

test("one comparison makes one compare call, whichever path records it", async () => {
  const f = fixture([]);
  const direct = compareOf({ files: [{ filename: "app/x.py", status: "modified" }] });
  const outcome = await recordSuiteComparison({ octokit: direct.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(outcome.ok, true);
  assert.equal(direct.calls.count, 1, "compare_suite_runs reads the compare once");
});

test("a delivery that goes on to record the comparison reuses the compare it already read", async () => {
  const f = fixture([]);
  const gate = compareOf({ files: [{ filename: "app/x.py", status: "modified" }] });
  const outcome = await runSuiteIfDue({ octokit: gate.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(outcome, "recorded");
  assert.equal(gate.calls.count, 1, "the definition check and the comparison share one compare response");
  assert.equal((f.store.get(suiteKey(REF, HEAD)) as { state?: string }).state, "clean");
});

test("a delivery that finds the run already recorded still makes only the one compare", async () => {
  const f = fixture([]);
  const gate = compareOf({ files: [{ filename: "app/x.py", status: "modified" }] });
  await runSuiteIfDue({ octokit: gate.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  const again = await runSuiteIfDue({ octokit: gate.octokit, kv: f.kv, ref: REF, headSha: HEAD, baseSha: BASE, reader: f.reader });
  assert.equal(again, "already-recorded");
  assert.equal(gate.calls.count, 2, "one compare per delivery, none extra");
});
