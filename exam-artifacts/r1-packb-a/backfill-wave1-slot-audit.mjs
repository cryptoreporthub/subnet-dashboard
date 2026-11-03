#!/usr/bin/env node
/** Backfill WAVE_1 audit lines only. V1 (model/sysprompt*) from wave-1 log preflight args — not from eval JSON. */
import { readFileSync, writeFileSync } from "node:fs";

const [jsonPath, auditPath, syspromptChars, syspromptShaArg, modelJson, fixturePinSha, packBV3] =
  process.argv.slice(2);
if (!jsonPath || !auditPath) {
  console.error(
    "usage: backfill-wave1-slot-audit.mjs <iter1.json> <audit.ndjson> <chars> <sha> <modelJson> <fixturePin> <true|false>",
  );
  process.exit(2);
}
const syspromptSha = syspromptShaArg ?? "";
if (syspromptSha.length !== 64) {
  console.error("STOP: sysprompt_sha256 missing or invalid for backfill");
  process.exit(3);
}
const model = JSON.parse(modelJson);
const doc = JSON.parse(readFileSync(jsonPath, "utf8"));
const derivation =
  "post_verdict, sessionId, durationMs from review-gate-r1packb-iter1 raw JSON; syspromptChars, syspromptSha256, model from wave-1 run log preflight lines only";
const lines = [];
for (const r of doc.results ?? []) {
  const id = r.id ?? "";
  const parts = id.split("/");
  const iteration = parts[parts.length - 1] ?? "?";
  const caseId = parts[parts.length - 2] ?? id;
  const postVerdict = (r.toolCalls ?? [])
    .filter((c) => c.toolName === "post_verdict")
    .map((c) => ({ args: c.args, output: c.output, isError: c.isError }));
  lines.push(
    JSON.stringify({
      caseId,
      iteration,
      evalId: id,
      model,
      syspromptChars: Number(syspromptChars),
      syspromptSha256: syspromptSha,
      packBV3GateSchema: packBV3 === "true",
      fixturePinSha: fixturePinSha || undefined,
      backfilled: true,
      backfillDerivation: derivation,
      postVerdict,
      sessionId: r.sessionId,
      durationMs: r.durationMs,
    }),
  );
}
writeFileSync(auditPath, `${lines.join("\n")}\n`);
