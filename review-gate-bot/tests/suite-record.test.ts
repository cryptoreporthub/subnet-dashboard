import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { recordSuiteComparison } from "../bot/lib/suite-record.js";
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
  assert.equal(f.store.get(suiteKey(REF, HEAD)), undefined, "a refusal records nothing");
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
