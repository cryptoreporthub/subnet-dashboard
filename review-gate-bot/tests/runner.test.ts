import assert from "node:assert/strict";
import test from "node:test";
import { deflateRawSync } from "node:zlib";
import {
  fetchJunit,
  junitFromEntries,
  pickArtifact,
  pickRun,
  readZip,
  type ArtifactRef,
  type RunnerReader,
} from "../bot/lib/runner.js";

/**
 * The zip writer here exists only so the reader is tested against real DEFLATE
 * bytes rather than a hand-built buffer. It writes the minimum a reader needs:
 * local header, one central-directory entry, end-of-central-directory.
 */
function zip(entries: { name: string; body: string; store?: boolean }[]): Uint8Array {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;

  for (const entry of entries) {
    const name = Buffer.from(entry.name, "utf8");
    const data = Buffer.from(entry.body, "utf8");
    const body = entry.store === true ? data : deflateRawSync(data);
    const method = entry.store === true ? 0 : 8;

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(0, 10);
    local.writeUInt32LE(0, 14);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    locals.push(local, name, body);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(0, 12);
    central.writeUInt32LE(0, 16);
    central.writeUInt32LE(body.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);

    offset += local.length + name.length + body.length;
  }

  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  return new Uint8Array(Buffer.concat([...locals, directory, end]));
}

const REPORT = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_a" name="one"/></testsuite></testsuites>';

test("readZip inflates a deflated entry and copies a stored one", () => {
  const entries = readZip(
    zip([
      { name: "junit.xml", body: REPORT },
      { name: "notes.txt", body: "hello", store: true },
    ]),
  );
  const names = entries.map((e) => e.name).sort();
  assert.deepEqual(names, ["junit.xml", "notes.txt"]);
  const xml = entries.find((e) => e.name === "junit.xml");
  assert.equal(new TextDecoder().decode(xml?.data), REPORT);
});

test("a truncated archive throws rather than returning no entries", () => {
  // The failure that mattered: an unreadable artifact must not silently read as
  // an empty suite.
  const bytes = zip([{ name: "junit.xml", body: REPORT }]);
  assert.throws(() => readZip(bytes.subarray(0, 10)), /truncated|central directory/);
});

test("an artifact with no JUnit report throws, naming what it did find", () => {
  assert.throws(
    () => junitFromEntries([{ name: "coverage.xml", data: new TextEncoder().encode("<x/>") }]),
    /no JUnit report .*coverage\.xml/,
  );
});

test("several sharded reports fold into one document", () => {
  const xml = junitFromEntries([
    { name: "junit-1.xml", data: new TextEncoder().encode(REPORT) },
    { name: "junit-2.xml", data: new TextEncoder().encode(REPORT.replace("one", "two")) },
  ]);
  assert.equal((xml.match(/<testsuites>/g) ?? []).length, 1, "exactly one root");
  assert.ok(xml.includes('name="one"'));
  assert.ok(xml.includes('name="two"'));
});

test("the artifact is picked by name, not by position", () => {
  const artifacts: ArtifactRef[] = [
    { id: 1, name: "coverage" },
    { id: 2, name: "pytest-junit" },
  ];
  assert.equal(pickArtifact(artifacts)?.id, 2);
  assert.equal(pickArtifact([{ id: 1, name: "coverage" }]), undefined);
});

test("the run is picked only when it has concluded", () => {
  assert.equal(pickRun([{ id: 7, conclusion: null }]), undefined);
  assert.equal(pickRun([{ id: 7, conclusion: "success" }])?.id, 7);
});

function reader(overrides: Partial<RunnerReader> = {}): RunnerReader {
  return {
    runsForSha: async () => [{ id: 7, conclusion: "success" }],
    artifactsForRun: async () => [{ id: 2, name: "pytest-junit" }],
    artifactZip: async () => zip([{ name: "junit.xml", body: REPORT }]),
    ...overrides,
  };
}

test("fetchJunit returns XML from the artifact for that SHA", async () => {
  const result = await fetchJunit(reader(), "a".repeat(40));
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.runId, 7);
    assert.ok(result.xml.includes("tests.test_a"));
  }
});

test("a SHA with no completed run is a refusal, never an empty report", async () => {
  const result = await fetchJunit(reader({ runsForSha: async () => [] }), "a".repeat(40));
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.reason, "no-run");
  }
});

test("a run with no artifact is a refusal that names the artifact", async () => {
  const result = await fetchJunit(reader({ artifactsForRun: async () => [] }), "a".repeat(40));
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.reason, "no-artifact");
    assert.ok(result.detail.includes("pytest-junit"));
  }
});

test("an unreadable artifact is a refusal", async () => {
  const result = await fetchJunit(
    reader({ artifactZip: async () => new Uint8Array([1, 2, 3]) }),
    "a".repeat(40),
  );
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.reason, "unreadable");
  }
});
