// Append-only judge journal for the AI judge verdict cache (PR 1522).
//
// Each record is written as a newline followed by one JSON line, in a single write call.
// Replay splits on newlines. Blank lines are skipped silently. Unparseable lines are
// skipped and counted. The last valid record per key wins.
//
// Durability is cache-only and never fsyncs. A successful append may not survive a crash,
// and the cache can always be regenerated.
// Multi-writer safety rests on O_APPEND. Local filesystems are tested. Network filesystems
// are allowed, but a line damaged by concurrent appends must replay as a miss, never as a
// different record. The one-eval-process rule still applies.
import { closeSync, constants, openSync, readFileSync, writeSync } from "node:fs";

export const JOURNAL_OPEN_FLAGS = constants.O_APPEND | constants.O_WRONLY | constants.O_CREAT;

/** Cap on the bytes written per append, measured with Buffer.byteLength (leading newline included). */
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

/**
 * Append one record. Throws if the record is over the byte cap (before touching the file),
 * if the open fails, or if the write is short. A short write is never retried, because a
 * retry could interleave with another writer's record. Never calls fsync.
 */
export function appendRecord(path: string, record: JournalRecord, options: AppendOptions = {}): void {
  const io = options.io ?? realIo;
  const maxBytes = options.maxBytes ?? MAX_RECORD_BYTES;
  const buf = Buffer.from("\n" + JSON.stringify(record), "utf8");
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
  /** Count of unparseable or malformed lines, anywhere in the file. Blank lines are not counted. */
  skipped: number;
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
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      skipped += 1;
      continue;
    }
    if (typeof parsed !== "object" || parsed === null || typeof (parsed as { key?: unknown }).key !== "string") {
      skipped += 1;
      continue;
    }
    const record = parsed as JournalRecord;
    hits.set(record.key, record);
  }
  return { hits, skipped };
}
