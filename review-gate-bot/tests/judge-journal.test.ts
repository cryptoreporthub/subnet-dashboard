// Tests for the append-only judge journal (bot/lib/judge-journal.ts).
// They cover record format, the checksum, replay rules, the byte cap, short and close errors,
// multi-writer appends on a local disk, and overlapping writes.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  appendFileSync,
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
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  JOURNAL_OPEN_FLAGS,
  MAX_RECORD_BYTES,
  appendRecord,
  encodeRecord,
  replayJournal,
  type JournalIo,
} from "../bot/lib/judge-journal.js";

function tempJournal(): string {
  return join(mkdtempSync(join(tmpdir(), "judge-journal-")), "judge.jsonl");
}

const realIo: JournalIo = {
  openSync: (p, flags) => openSync(p, flags, 0o644),
  writeSync: (fd, buf) => writeSync(fd, buf),
  closeSync: (fd) => closeSync(fd),
};

// Encoded length of a record with a verdict of `n` characters. The length is linear in n.
function encodedLength(n: number): number {
  return Buffer.byteLength(encodeRecord({ key: "k", verdict: "x".repeat(n) }));
}

// 1. Explicit O_APPEND.
test("journal opens the file with O_APPEND|O_WRONLY|O_CREAT", () => {
  assert.equal(JOURNAL_OPEN_FLAGS, constants.O_APPEND | constants.O_WRONLY | constants.O_CREAT);
});

// 2. Each append writes exactly its encoded line, one after another.
test("appends write each record's encoded line in order", () => {
  const path = tempJournal();
  const a = { key: "k1", verdict: "PASS" };
  const b = { key: "k2", verdict: "MODIFY" };
  appendRecord(path, a, { io: realIo });
  appendRecord(path, b, { io: realIo });
  assert.equal(readFileSync(path, "utf8"), encodeRecord(a) + encodeRecord(b));
});

// 3. A torn fragment followed by a good append still replays the good record, and the torn one is a miss.
test("a torn fragment followed by a good append still replays the good record as a hit", () => {
  const path = tempJournal();
  appendRecord(path, { key: "old", verdict: "PASS" }, { io: realIo });
  const whole = readFileSync(path, "utf8");
  writeFileSync(path, whole.slice(0, -12)); // writer died mid-append, no trailing newline
  appendRecord(path, { key: "new", verdict: "PASS" }, { io: realIo });
  const { hits } = replayJournal(path);
  assert.deepEqual(hits.get("new"), { key: "new", verdict: "PASS" });
  assert.equal(hits.has("old"), false, "torn fragment must read as a miss, never a hit");
});

// 4. Blank lines are skipped without being counted as malformed.
test("blank lines are skipped and not reported as malformed", () => {
  const path = tempJournal();
  appendRecord(path, { key: "a", verdict: "PASS" }, { io: realIo });
  appendFileSync(path, "\n\n");
  const result = replayJournal(path);
  assert.deepEqual(result.hits.get("a"), { key: "a", verdict: "PASS" });
  assert.equal(result.skipped, 0);
});

// 5. Last valid record per key wins.
test("replay takes the last valid record per key", () => {
  const path = tempJournal();
  appendRecord(path, { key: "a", verdict: "MODIFY" }, { io: realIo });
  appendRecord(path, { key: "a", verdict: "PASS" }, { io: realIo });
  assert.equal(replayJournal(path).hits.get("a")?.verdict, "PASS");
});

// 6. A malformed line in the middle is skipped and reported, and replay continues.
test("a malformed line in the middle is skipped, reported, and replay continues", () => {
  const path = tempJournal();
  appendRecord(path, { key: "a", verdict: "PASS" }, { io: realIo });
  appendFileSync(path, '\n{"body":"{\\"key\\":\\"b\\",\\"verd');
  appendRecord(path, { key: "c", verdict: "MODIFY" }, { io: realIo });
  const result = replayJournal(path);
  assert.equal(result.hits.get("a")?.verdict, "PASS");
  assert.equal(result.hits.get("c")?.verdict, "MODIFY");
  assert.equal(result.hits.has("b"), false);
  assert.equal(result.skipped, 1);
});

// 7. A short write throws; the writer does not report success.
test("a short write throws and the writer does not report success", () => {
  const path = tempJournal();
  const shortIo: JournalIo = { ...realIo, writeSync: (fd, buf) => realIo.writeSync(fd, buf) - 1 };
  assert.throws(() => appendRecord(path, { key: "k", verdict: "PASS" }, { io: shortIo }));
});

// 8. A short write is not retried, because a retry could interleave with another writer's record.
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

// 9. Over the cap throws, measured in bytes, and the file is not touched.
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
  const fill = "x".repeat(MAX_RECORD_BYTES - encodedLength(0));
  appendRecord(path, { key: "k", verdict: fill }, { io: realIo });
  assert.equal(replayJournal(path).hits.get("k")?.verdict, fill);
});

// 11. One byte over the cap throws.
test("a record one byte over the cap throws", () => {
  const path = tempJournal();
  const fill = "x".repeat(MAX_RECORD_BYTES - encodedLength(0) + 1);
  assert.throws(() => appendRecord(path, { key: "k", verdict: fill }, { io: realIo }));
  assert.equal(existsSync(path), false);
});

// 12. A missing journal replays as empty, so every key is a miss.
test("a missing journal replays as empty, every key a miss", () => {
  const path = join(mkdtempSync(join(tmpdir(), "judge-journal-")), "nope.jsonl");
  const result = replayJournal(path);
  assert.equal(result.hits.size, 0);
  assert.equal(result.skipped, 0);
});

// 13. Local filesystem only. Four writer processes keep all 1,200 records.
// Not evidence for network filesystems.
test("local filesystem: four writer processes keep all 1,200 records intact", async () => {
  const path = tempJournal();
  const moduleUrl = new URL("../bot/lib/judge-journal.ts", import.meta.url).href;
  const writerSource = `
    import { appendRecord } from "${moduleUrl}";
    const id = Number(process.argv[2]);
    for (let i = 0; i < 300; i++) {
      appendRecord(process.argv[3], { key: "w" + id + "-" + i, verdict: "PASS", pad: "x".repeat(200 + (i % 3) * 1000) }, {});
    }
  `;
  const writerPath = join(path, "..", "writer.mts");
  writeFileSync(writerPath, writerSource);
  const packageDir = fileURLToPath(new URL("..", import.meta.url));
  const runs = [0, 1, 2, 3].map(
    (id) =>
      new Promise<void>((resolve, reject) => {
        const child = spawn(process.execPath, ["--import", "tsx", writerPath, String(id), path], {
          stdio: "inherit",
          cwd: packageDir,
        });
        child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`writer ${id} exited ${code}`))));
      }),
  );
  await Promise.all(runs);
  const result = replayJournal(path);
  assert.equal(result.skipped, 0);
  assert.equal(result.hits.size, 1200);
});

// 14. Overlapping writes may lose records, but replay never returns a record no writer wrote.
// Deterministic offsets, so the test does not depend on randomness.
test("overlapping offset writes never replay as a record no writer wrote", () => {
  const dir = mkdtempSync(join(tmpdir(), "judge-journal-overlap-"));
  for (let trial = 0; trial < 500; trial++) {
    const path = join(dir, `t${trial}.jsonl`);
    const count = 2 + (trial % 3);
    const records: { key: string; verdict: string; pad: string }[] = [];
    const lines: string[] = [];
    const fd = openSync(path, "w");
    try {
      for (let i = 0; i < count; i++) {
        const pad = String.fromCharCode(97 + i).repeat(5 + ((trial * 7 + i * 13) % 90));
        const record = { key: `k${i}`, verdict: i % 2 ? "PASS" : "MODIFY", pad };
        const line = encodeRecord(record);
        records.push(record);
        lines.push(line);
        const offset = i === 0 ? 0 : (trial * 31 + i * 17) % (lines[i - 1].length + 1);
        writeSync(fd, Buffer.from(line), 0, Buffer.byteLength(line), offset);
      }
    } finally {
      closeSync(fd);
    }
    const written = new Set(records.map((r) => JSON.stringify(r)));
    for (const record of replayJournal(path).hits.values()) {
      assert.ok(written.has(JSON.stringify(record)), `trial ${trial}: replayed a record no writer wrote`);
    }
  }
});

// 15. A close error after a successful write is thrown.
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

// 16. A close error does not hide the short-write error that already happened.
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

// 17. A line with a valid checksum but no string key is not a record. It is skipped and counted.
test("a keyless or non-string-key record is skipped and counted, not replayed as a hit", () => {
  const path = tempJournal();
  writeFileSync(
    path,
    encodeRecord({ verdict: "PASS" } as never) +
      encodeRecord({ key: 42, verdict: "PASS" } as never) +
      encodeRecord({ key: "ok", verdict: "MODIFY" }),
  );
  const result = replayJournal(path);
  assert.equal(result.hits.get("ok")?.verdict, "MODIFY");
  assert.equal(result.hits.size, 1);
  assert.equal(result.skipped, 2);
});

// 18. A damaged line that still parses must read as a miss, never as a different record.
test("a parseable line whose value was changed reads as a miss", () => {
  const path = tempJournal();
  appendRecord(path, { key: "judge:sha", verdict: "PASS" }, { io: realIo });
  const damaged = readFileSync(path, "utf8").replace("PASS", "FAIL");
  writeFileSync(path, damaged);
  const result = replayJournal(path);
  assert.equal(result.hits.has("judge:sha"), false);
  assert.equal(result.skipped, 1);
});
