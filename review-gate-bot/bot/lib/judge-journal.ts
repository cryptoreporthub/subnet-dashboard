// Append-only judge journal for the judge verdict cache (PR 1522).
//
// Each record is one line, written in a single O_APPEND write:
//   "\n" + JSON.stringify({ body, sum })
// where body is the record's JSON text and sum is the first 16 hex digits of its SHA-256.
// Replay splits on newlines. Blank lines are skipped silently. A line that does not parse,
// does not verify its sum, or has no string key is skipped and counted. The last valid record
// per key wins. A damaged line reads as a miss, never as a different record. But if a newer
// record for a key is damaged or lost, replay falls back to the older record for that key,
// so the cache can serve an older verdict for that key. Callers must accept that.
//
// Durability is cache-only and never fsyncs. A successful append may not survive a crash,
// and the cache can always be regenerated.
// Multi-writer safety rests on O_APPEND. Local filesystems are tested. Network filesystems are
// allowed, and the checksum is the guard against damaged lines.
// The one-eval-process rule still applies.
import { createHash } from "node:crypto";
import { closeSync, constants, openSync, readFileSync, writeSync } from "node:fs";

export const JOURNAL_OPEN_FLAGS = constants.O_APPEND | constants.O_WRONLY | constants.O_CREAT;

/** Cap on the bytes written per append: the full encoded line, measured with Buffer.byteLength. */
export const MAX_RECORD_BYTES = 4096;

export interface JournalRecord {
  key: string;
  [field: string]: unknown;
}

export interface JournalIo {
  openSync(path: string, flags: number): number;
  writeSync(fd: number, buf: Buffer): number;
  closeSync(fd: number): void;
}

const realIo: JournalIo = {
  openSync: (path, flags) => openSync(path, flags, 0o644),
  writeSync: (fd, buf) => writeSync(fd, buf),
  closeSync: (fd) => closeSync(fd),
};

export interface AppendOptions {
  io?: JournalIo;
  maxBytes?: number;
}

function checksum(body: string): string {
  return createHash("sha256").update(body, "utf8").digest("hex").slice(0, 16);
}

/** The exact text appendRecord writes for a record, including the leading newline. */
export function encodeRecord(record: JournalRecord): string {
  const body = JSON.stringify(record);
  return "\n" + JSON.stringify({ body, sum: checksum(body) });
}

/**
 * Append one record. Throws if the record is over the byte cap (before touching the file),
 * if the open fails, or if the write is short. A short write is never retried, because a
 * retry could interleave with another writer's record. Never calls fsync.
 */
export function appendRecord(path: string, record: JournalRecord, options: AppendOptions = {}): void {
  const io = options.io ?? realIo;
  const maxBytes = options.maxBytes ?? MAX_RECORD_BYTES;
  const buf = Buffer.from(encodeRecord(record), "utf8");
  if (buf.length > maxBytes) {
    throw new Error(`judge journal record is ${buf.length} bytes, over the ${maxBytes}-byte cap`);
  }
  const fd = io.openSync(path, JOURNAL_OPEN_FLAGS);
  let failed = false;
  try {
    const written = io.writeSync(fd, buf);
    if (written !== buf.length) {
      throw new Error(`judge journal short write: ${written} of ${buf.length} bytes`);
    }
  } catch (err) {
    failed = true;
    throw err;
  } finally {
    // A close error still surfaces when the write succeeded (network mounts can defer write errors
    // to close), but it must not hide the write error that already happened.
    try {
      io.closeSync(fd);
    } catch (closeErr) {
      if (!failed) throw closeErr;
    }
  }
}

export interface ReplayResult {
  /** Last valid record per key. A key not present here is a miss. */
  hits: Map<string, JournalRecord>;
  /** Count of unparseable, unverified, or malformed lines, anywhere in the file. Blank lines are not counted. */
  skipped: number;
}

function decodeLine(line: string): JournalRecord | undefined {
  let envelope: unknown;
  try {
    envelope = JSON.parse(line);
  } catch {
    return undefined;
  }
  if (typeof envelope !== "object" || envelope === null) return undefined;
  const { body, sum } = envelope as { body?: unknown; sum?: unknown };
  if (typeof body !== "string" || typeof sum !== "string" || checksum(body) !== sum) return undefined;
  let record: unknown;
  try {
    record = JSON.parse(body);
  } catch {
    return undefined;
  }
  if (typeof record !== "object" || record === null || typeof (record as { key?: unknown }).key !== "string") {
    return undefined;
  }
  return record as JournalRecord;
}

/** Replay the journal. A missing file replays as empty. */
export function replayJournal(path: string): ReplayResult {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return { hits: new Map(), skipped: 0 };
    }
    throw err;
  }
  const hits = new Map<string, JournalRecord>();
  let skipped = 0;
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    const record = decodeLine(line);
    if (record === undefined) {
      skipped += 1;
      continue;
    }
    hits.set(record.key, record);
  }
  return { hits, skipped };
}
