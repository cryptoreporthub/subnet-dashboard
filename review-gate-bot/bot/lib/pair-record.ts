import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { RecordedSuite } from "./gh.js";
import { readSuiteRecord, legacySuiteKey, suiteKey, type PrRef } from "./gh.js";
import type { ReadyPair } from "./pair-observation.js";

/** Reader-expected schema version for pair-key suite records (plan §3). */
export const READER_EXPECTED_SCHEMA_VERSION = 1;

export const RECORD_VERSION_MISMATCH_DETAIL = "record-version-mismatch, recompute due";
export const RECORD_RECOMPUTED_DETAIL = "recomputed";

export type InvalidPairRecordReason = "record-version-mismatch" | "merge-base-mismatch";

export type ValidPairRecord = { ok: true; record: RecordedSuite };
export type InvalidPairRecord = { ok: false; reason: InvalidPairRecordReason; detail: string };

export type ParsePairRecordResult = ValidPairRecord | InvalidPairRecord;

/**
 * Validate a pair-key record against live ReadyPair: schema version and merge-base match.
 * Legacy head-only holds (Policy-H1) pass through without pair schema when flagged.
 */
export function validatePairRecordForReadyPair(record: RecordedSuite | undefined, live: ReadyPair): ParsePairRecordResult {
  if (record === undefined) {
    return { ok: false, reason: "record-version-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  const v = (record as { schemaVersion?: unknown }).schemaVersion;
  if (v !== READER_EXPECTED_SCHEMA_VERSION) {
    return { ok: false, reason: "record-version-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  const mb = (record as { mergeBaseSha?: unknown }).mergeBaseSha;
  if (typeof mb !== "string" || !/^[0-9a-f]{40}$/.test(mb)) {
    return { ok: false, reason: "merge-base-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  if (mb !== live.mergeBaseSha) {
    return { ok: false, reason: "merge-base-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  return { ok: true, record };
}

/**
 * Read suite record and validate for trust. Legacy needs-joshua head hold returns Valid without pair schema (H1).
 */
export async function readSuiteRecordTrusted(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
  baseTipSha: string | undefined,
  live: ReadyPair,
): Promise<ParsePairRecordResult> {
  const legacy = (await kv.get(legacySuiteKey(ref, headSha))) as RecordedSuite | undefined;
  if (legacy !== undefined && typeof legacy === "object" && legacy.invalid === "needs-joshua") {
    return { ok: true, record: legacy as RecordedSuite };
  }
  if (baseTipSha === undefined || baseTipSha === "") {
    return { ok: false, reason: "merge-base-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  const raw = await readSuiteRecord(kv, ref, headSha, baseTipSha);
  if (raw === undefined) {
    return { ok: false, reason: "record-version-mismatch", detail: RECORD_VERSION_MISMATCH_DETAIL };
  }
  if (raw.invalid === "needs-joshua") {
    return { ok: true, record: raw };
  }
  return validatePairRecordForReadyPair(raw, live);
}
