import assert from "node:assert/strict";
import test from "node:test";
import { deflateRawSync } from "node:zlib";
import type { Octokit } from "@octokit/rest";
import {
  downloadViaRedirect,
  MAX_ARCHIVE_BYTES,
  readCappedBody,
  MAX_ENTRY_BYTES,
  fetchJunit,
  junitFromEntries,
  octokitRunner,
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
function zip(entries: { name: string; body: string; store?: boolean; declaredSize?: number }[]): Uint8Array {
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
    central.writeUInt32LE(entry.declaredSize ?? data.length, 24);
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

test("entries that declare zero bytes but inflate past the archive cap are refused", () => {
  // The declared size is the attacker's claim. Three entries that each inflate
  // to the per-entry limit are 3 x 64 MiB against a 128 MiB archive cap.
  const body = "\0".repeat(MAX_ENTRY_BYTES);
  const entries = [0, 1, 2].map((n) => ({ name: `junit-${n}.xml`, body, declaredSize: 0 }));
  assert.throws(() => readZip(zip(entries)), /excessive inflated size|too large/);
});

test("entries that inflate within the archive cap are read whatever size they declare", () => {
  const entries = readZip(zip([{ name: "junit.xml", body: REPORT, declaredSize: 0 }]));
  assert.equal(new TextDecoder().decode(entries[0]?.data), REPORT);
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

const SIGNED = "https://productionresultssa19.blob.core.windows.net/actions-results/abc?sig=x";

// --- What the real download path does: a 302 to a signed storage host --------

/**
 * The smallest Octokit that answers the calls the runner makes. The artifact
 * endpoint answers with a redirect, as the real one does, and the bytes come
 * from a stubbed `fetch` to the signed URL.
 */
function octokitServing(): Octokit {
  return {
    rest: {
      actions: {
        listWorkflowRuns: async () => ({ data: { workflow_runs: [{ id: 7, conclusion: "success" }] } }),
        listWorkflowRunArtifacts: async () => ({ data: { artifacts: [{ id: 2, name: "pytest-junit" }] } }),
      },
    },
    request: async () => ({ headers: { location: SIGNED } }),
  } as unknown as Octokit;
}

async function withStorage<T>(respond: () => Response, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => respond()) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("the real runner reads a zip served from the signed storage URL", async () => {
  const archive = zip([{ name: "junit.xml", body: REPORT }]);
  const body = archive.buffer.slice(archive.byteOffset, archive.byteOffset + archive.byteLength) as ArrayBuffer;
  const result = await withStorage(
    () => new Response(body),
    () => fetchJunit(octokitRunner(octokitServing(), { owner: "o", repo: "r" }), "a".repeat(40)),
  );
  assert.equal(result.ok, true, JSON.stringify(result));
  if (result.ok) {
    assert.ok(result.xml.includes('name="one"'));
  }
});

test("a download that is not a zip is an unreadable refusal, not a crash", async () => {
  const result = await withStorage(
    () => new Response("<html>not a zip</html>"),
    () => fetchJunit(octokitRunner(octokitServing(), { owner: "o", repo: "r" }), "a".repeat(40)),
  );
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.reason, "unreadable");
  }
});

test("a storage host that answers with an error is an unreadable refusal that names the host", async () => {
  const result = await withStorage(
    () => new Response("denied", { status: 403 }),
    () => fetchJunit(octokitRunner(octokitServing(), { owner: "o", repo: "r" }), "a".repeat(40)),
  );
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.reason, "unreadable");
    assert.match(result.detail, /productionresultssa19\.blob\.core\.windows\.net/);
  }
});

test("reports/pytest.xml, the path the README tells the workflow to write, is accepted", () => {
  const xml = junitFromEntries([{ name: "reports/pytest.xml", data: new TextEncoder().encode(REPORT) }]);
  assert.ok(xml.includes('name="one"'));
});

test("a shard cut off before its closing root tag is refused, not repaired", () => {
  const cut = REPORT.replace("</testsuites>", "");
  assert.throws(
    () => junitFromEntries([{ name: "junit-1.xml", data: new TextEncoder().encode(cut) }]),
    /junit-1\.xml.*malformed/i,
  );
});

// --- Second review: which runs count, and how much a report may inflate ----

test("a cancelled, timed-out or skipped run is not a result", () => {
  for (const conclusion of ["cancelled", "timed_out", "skipped", "startup_failure", "action_required", "stale"]) {
    assert.equal(pickRun([{ id: 7, conclusion }]), undefined, conclusion);
  }
});

test("a run that finished, passing or failing, is a result; the newest comes first", () => {
  assert.equal(pickRun([{ id: 9, conclusion: "cancelled" }, { id: 8, conclusion: "failure" }, { id: 7, conclusion: "success" }])?.id, 8);
  assert.equal(pickRun([{ id: 7, conclusion: "neutral" }])?.id, 7);
});

test("an entry that declares more than the cap is refused before anything is inflated", () => {
  const big = "0".repeat(70 * 1024 * 1024);
  assert.throws(() => readZip(zip([{ name: "junit.xml", body: big }])), /too large|exceeds/i);
});

test("many entries cannot add up past the total cap", () => {
  const each = "0".repeat(20 * 1024 * 1024);
  const entries = Array.from({ length: 8 }, (_, i) => ({ name: `junit-${i}.xml`, body: each }));
  assert.throws(() => readZip(zip(entries)), /total|too large|exceeds/i);
});

test("an archive with a very large number of entries is refused", () => {
  const entries = Array.from({ length: 2_000 }, (_, i) => ({ name: `f${i}.txt`, body: "x", store: true }));
  assert.throws(() => readZip(zip(entries)), /entries|too many/i);
});

test("the artifact is fetched from the Actions storage host the redirect names", async () => {
  const bytes = new Uint8Array([80, 75, 3, 4]);
  let fetched = "";
  const got = await downloadViaRedirect({
    locate: async () => SIGNED,
    fetchBytes: async (url) => {
      fetched = url;
      return bytes;
    },
  });
  assert.deepEqual(got, bytes);
  assert.equal(fetched, SIGNED);
});

test("a redirect to any other host is refused before a byte is fetched", async () => {
  let called = false;
  await assert.rejects(
    downloadViaRedirect({
      locate: async () => "https://evil.example.com/steal?sig=x",
      fetchBytes: async () => {
        called = true;
        return new Uint8Array();
      },
    }),
    /evil\.example\.com/,
  );
  assert.equal(called, false);
});

test("a look-alike host that only ends with the storage name is refused", async () => {
  await assert.rejects(
    downloadViaRedirect({
      locate: async () => "https://productionresultssa19.blob.core.windows.net.evil.test/x",
      fetchBytes: async () => new Uint8Array(),
    }),
    /evil\.test/,
  );
});

test("a refused connection names the host so an egress block can be read off the reason", async () => {
  await assert.rejects(
    downloadViaRedirect({
      locate: async () => SIGNED,
      fetchBytes: async () => {
        throw new Error("fetch failed");
      },
    }),
    /productionresultssa19\.blob\.core\.windows\.net.*egress/s,
  );
});

test("no redirect location at all is a refusal, not an empty report", async () => {
  await assert.rejects(
    downloadViaRedirect({ locate: async () => undefined, fetchBytes: async () => new Uint8Array() }),
    /redirect/i,
  );
});

test("an artifact whose declared size is past the download ceiling is refused before its body is read", async () => {
  const declared = new Response(new Uint8Array(16), { headers: { "content-length": String(MAX_ARCHIVE_BYTES + 1) } });
  await assert.rejects(readCappedBody(declared, MAX_ARCHIVE_BYTES), /ceiling/);
});

test("an artifact body that streams past the ceiling is cut off as it arrives, not buffered whole", async () => {
  let pulled = 0;
  const chunk = new Uint8Array(1024 * 1024);
  const endless = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulled += 1;
      if (pulled > 1000) {
        controller.close();
        return;
      }
      controller.enqueue(chunk);
    },
  });
  await assert.rejects(readCappedBody(new Response(endless), 4 * 1024 * 1024), /ceiling/);
  assert.ok(pulled < 20, `read ${pulled} chunks before stopping; the ceiling should stop it after about 5`);
});

test("an artifact within the ceiling is read whole", async () => {
  const body = new Uint8Array([1, 2, 3, 4, 5]);
  const bytes = await readCappedBody(new Response(body), 1024);
  assert.deepEqual([...bytes], [1, 2, 3, 4, 5]);
});
