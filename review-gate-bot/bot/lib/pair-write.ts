import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { RecordedSuite } from "./gh.js";
import { suiteKey, type PrRef } from "./gh.js";
import { READER_EXPECTED_SCHEMA_VERSION } from "./pair-record.js";

/**
 * Sole writer for pair-key `suite:` KV records (RD-07).
 * Callers supply merge-base and body; schema version is always the reader-expected value.
 */
export async function writePairResult(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
  baseTipSha: string,
  mergeBaseSha: string,
  body: Omit<RecordedSuite, "schemaVersion" | "mergeBaseSha" | "checkHoldFingerprint"> & {
    checkHoldFingerprint: string;
  },
): Promise<void> {
  const record: RecordedSuite = {
    schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
    mergeBaseSha,
    ...body,
  };
  await kv.put(suiteKey(ref, headSha, baseTipSha), record);
}
