// Tests for the append-only judge journal (bot/lib/judge-journal.ts).
// They cover record format, replay rules, the byte cap, short and close errors,
// multi-writer appends on a local disk, and overlapping writes.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  closeSync,
  constants,
  existsSync,
  mkdtempSync,
  openSync,
  readFileSync,
  writeFileSync,
  writeSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  JOURNAL_OPEN_FLAGS,
  MAX_RECORD_BYTES,
  appendRecord,
  replayJournal,
  type JournalIo,
} from "../bot/lib/judge-journal.js";

function tempJournal(): string {
  const dir = mkdtempSync(join(tmpdir(), "judge-journal-"));
  return join(dir, "judge.jsonl");
}

const realIo: JournalIo = {
  openSync: (p, flags) => openSync(p, flags),
  writeSync: (fd, buf) => writeSync(fd, buf),
  closeSync: (fd) => closeSync(fd),
};

// 1. Explicit O_APPEND.
test("journal opens the file with O_APPEND|O_WRONLY|O_CREAT", () => {
  assert.equal(
    JOURNAL_OPEN_FLAGS,
    constants.O_APPEND | constants.O_WRONLY | constants.O_CREAT,
  );
});

// 2. One record, one line, written in one call.
test("append writes exactly one newline-prefixed JSON line per record", () => {
  const path = tempJournal();
  appendRecord(path, { key: "k1", verdict: "PASS" }, { io: realIo });
  appendRecord(path, { key: "k2", verdict: "MODIFY" }, { io: realIo });
  const raw = readFileSync(path, "utf8");
  assert.equal(raw, '\n{"key":"k1","verdict":"PASS"}\n{"key":"k2","verdict":"MODIFY"}');
});

// 3. Glued-record fix: a torn fragment must not swallow the next record.
test("a torn fragment followed by a good append still replays the good record as a hit", () => {
  const path = tempJournal();
  writeFileSync(path, '\n{"key":"old","verdict":"PA'); // writer died mid-append, no trailing newline
  appendRecord(path, { key: "new", verdict: "PASS" }, { io: realIo });
  const { hits } = replayJournal(path);
  assert.deepEqual(hits.get("new"), { key: "new", verdict: "PASS" });
  assert.equal(hits.has("old"), false, "torn fragment must read as a miss, never a hit");
});

// 4. Blank lines are skipped without being counted as malformed.
test("blank lines are skipped and not reported as malformed", () => {
  const path = tempJournal();
  writeFileSync(path, '\n\n{"key":"a","verdict":"PASS"}\n\n');
  const result = replayJournal(path);
  assert.deepEqual(result.hits.get("a"), { key: "a", verdict: "PASS" });
  assert.equal(result.skipped, 0);
});

// 5. Last valid record per key wins (final rule, decided 2026-11-16).
test("replay takes the last valid record per key", () => {
  const path = tempJournal();
  writeFileSync(
    path,
    '\n{"key":"a","verdict":"MODIFY"}\n{"key":"a","verdict":"PASS"}\n',
  );
  assert.equal(replayJournal(path).hits.get("a")?.verdict, "PASS");
});

// 6. Malformed interior line is skipped and reported, and replay continues.
test("a malformed line in the middle is skipped, reported, and replay continues", () => {
  const path = tempJournal();
  writeFileSync(path, '\n{"key":"a","verdict":"PASS"}\n{"key":"b","verd\n{"key":"c","verdict":"MODIFY"}\n');
  const result = replayJournal(path);
  assert.equal(result.hits.get("a")?.verdict, "PASS");
  assert.equal(result.hits.get("c")?.verdict, "MODIFY");
  assert.equal(result.hits.has("b"), false);
  assert.equal(result.skipped, 1);
});

// 7. Short write throws; the writer must not report success.
test("a short write throws and the writer does not report success", () => {
  const path = tempJournal();
  const shortIo: JournalIo = {
    ...realIo,
    writeSync: (fd, buf) => realIo.writeSync(fd, buf) - 1,
  };
  assert.throws(() => appendRecord(path, { key: "k", verdict: "PASS" }, { io: shortIo }));
});

// 8. No retry on a short write: a retry could interleave with another writer's record.
test("a short write is not retried", () => {
  const path = tempJournal();
  let calls = 0;
  const shortIo: JournalIo = {
    ...realIo,
    writeSync: (fd, buf) => {
      calls += 1;
      return realIo.writeSync(fd, buf) - 1;
    },
  };
  assert.throws(() => appendRecord(path, { key: "k", verdict: "PASS" }, { io: shortIo }));
  assert.equal(calls, 1);
});

// 9. Over-cap throws; measured in bytes, not string length (Buffer.byteLength).
test("a record over the byte cap throws, measured in bytes", () => {
  const path = tempJournal();
  // "é" is 2 bytes in UTF-8, so the string is shorter than its byte length.
  const big = "é".repeat(Math.floor(MAX_RECORD_BYTES / 2) + 10);
  assert.throws(() => appendRecord(path, { key: "k", verdict: big }, { io: realIo }));
  assert.equal(existsSync(path), false, "an over-cap record must not touch the file");
});

// 10. Boundary: exactly at the cap is accepted.
test("a record exactly at the byte cap is accepted", () => {
  const path = tempJournal();
  const head = '{"key":"k","verdict":"';
  const tail = '"}';
  // Line content plus the leading newline must fit within the cap.
  const fill = "x".repeat(MAX_RECORD_BYTES - Buffer.byteLength(head + tail) - 1);
  appendRecord(path, { key: "k", verdict: fill }, { io: realIo });
  assert.equal(replayJournal(path).hits.get("k")?.verdict, fill);
});

// 11. Missing file replays as empty, so every key is a miss.
test("a missing journal replays as empty, every key a miss", () => {
  const path = join(mkdtempSync(join(tmpdir(), "judge-journal-")), "nope.jsonl");
  const result = replayJournal(path);
  assert.equal(result.hits.size, 0);
  assert.equal(result.skipped, 0);
});

// 12. Local-filesystem evidence only: concurrent writer processes keep every record (4 writers x 300 records).
// Not evidence for network filesystems.
test("local filesystem: four writer processes keep all 1,200 records intact", async () => {
  const path = tempJournal();
  const writer = `
    import { appendRecord } from "${fileURLToPath(new URL("../bot/lib/judge-journal.ts", import.meta.url))}";
    const id = Number(process.argv[2]);
    for (let i = 0; i < 300; i++) {
      appendRecord(process.argv[3], { key: "w" + id + "-" + i, verdict: "PASS", pad: "x".repeat(200 + (i % 3) * 1000) }, {});
    }
  `;
  const writerPath = join(path, "..", "writer.mts");
  writeFileSync(writerPath, writer);
  const runs = [0, 1, 2, 3].map(
    (id) =>
      new Promise<void>((resolve, reject) => {
        const child = spawn(process.execPath, ["--import", "tsx", writerPath, String(id), path], {
          stdio: "inherit",
          cwd: fileURLToPath(new URL("..", import.meta.url)),
        });
        child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`writer ${id} exited ${code}`))));
      }),
  );
  await Promise.all(runs);
  const result = replayJournal(path);
  assert.equal(result.skipped, 0);
  assert.equal(result.hits.size, 1200);
});

// 13. Overlapping writes (the NFS-style race) may lose records, but replay must never return a
// record that no writer wrote. Deterministic offsets, so the test does not depend on randomness.
test("overlapping offset writes never replay as a record no writer wrote", () => {
  const dir = mkdtempSync(join(tmpdir(), "judge-journal-overlap-"));
  for (let trial = 0; trial < 500; trial++) {
    const path = join(dir, `t${trial}.jsonl`);
    const count = 2 + (trial % 3);
    const lines: string[] = [];
    const fd = openSync(path, "w");
    try {
      for (let i = 0; i < count; i++) {
        const pad = String.fromCharCode(97 + i).repeat(5 + ((trial * 7 + i * 13) % 90));
        const line = "\n" + JSON.stringify({ key: `k${i}`, verdict: i % 2 ? "PASS" : "MODIFY", pad });
        lines.push(line);
        const offset = i === 0 ? 0 : (trial * 31 + i * 17) % (lines[i - 1].length + 1);
        writeSync(fd, Buffer.from(line), 0, Buffer.byteLength(line), offset);
      }
    } finally {
      closeSync(fd);
    }
    const written = new Set(lines.map((l) => l.slice(1)));
    for (const record of replayJournal(path).hits.values()) {
      assert.ok(written.has(JSON.stringify(record)), `trial ${trial}: replayed a record no writer wrote`);
    }
  }
});

// 14. A close error after a successful write still surfaces (network mounts can defer write errors to close).
test("a close error after a successful write is thrown", () => {
  const path = tempJournal();
  const closeFailIo: JournalIo = {
    ...realIo,
    closeSync: (fd) => {
      realIo.closeSync(fd);
      throw new Error("close failed");
    },
  };
  assert.throws(() => appendRecord(path, { key: "k", verdict: "PASS" }, { io: closeFailIo }), /close failed/);
});

// 15. A close error must not hide the short-write error that already happened.
test("a close error does not mask an earlier short-write error", () => {
  const path = tempJournal();
  const bothFailIo: JournalIo = {
    ...realIo,
    writeSync: (fd, buf) => realIo.writeSync(fd, buf) - 1,
    closeSync: (fd) => {
      realIo.closeSync(fd);
      throw new Error("close failed");
    },
  };
  assert.throws(() => appendRecord(path, { key: "k", verdict: "PASS" }, { io: bothFailIo }), /short write/);
});

// Cap+1 must throw, so a loosened comparison is caught.
test("a record one byte over the cap throws", () => {
  const path = tempJournal();
  const head = '{"key":"k","verdict":"';
  const tail = '"}';
  const fill = "x".repeat(MAX_RECORD_BYTES - Buffer.byteLength(head + tail));
  assert.throws(() => appendRecord(path, { key: "k", verdict: fill }, { io: realIo }));
  assert.equal(existsSync(path), false);
});

// A JSON line without a string key is not a record and must be skipped and counted.
test("a keyless JSON line is skipped and counted, not replayed as a hit", () => {
  const path = tempJournal();
  writeFileSync(path, '\n{"verdict":"PASS"}\n{"key":42,"verdict":"PASS"}\n{"key":"ok","verdict":"MODIFY"}');
  const result = replayJournal(path);
  assert.equal(result.hits.get("ok")?.verdict, "MODIFY");
  assert.equal(result.hits.size, 1);
  assert.equal(result.skipped, 2);
});
