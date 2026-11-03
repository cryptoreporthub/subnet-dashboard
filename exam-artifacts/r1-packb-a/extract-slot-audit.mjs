#!/usr/bin/env node
/** Append per-slot audit lines from raw agent-sdk eval JSON (no scoring). V1: syspromptSha256 required. */
import { createHash } from "node:crypto";
import { readFileSync, appendFileSync } from "node:fs";

const [jsonPath, auditPath, syspromptChars, syspromptShaArg, modelJson, fixturePinSha, packBV3] = process.argv.slice(2);
if (!jsonPath || !auditPath) {
  console.error("usage: extract-slot-audit.mjs <eval.json> <audit.ndjson> <chars> <sha> <modelJson>");
  process.exit(2);
}
let syspromptSha = syspromptShaArg ?? "";
if (!syspromptSha || syspromptSha.length !== 64) {
  console.error("STOP: sysprompt_sha256 missing or invalid for audit line");
  process.exit(3);
}
const doc = JSON.parse(readFileSync(jsonPath, "utf8"));
const model = JSON.parse(modelJson);
for (const r of doc.results ?? []) {
  const id = r.id ?? "";
  const parts = id.split("/");
  const iteration = parts[parts.length - 1] ?? "?";
  const caseId = parts[parts.length - 2] ?? id;
  const postVerdict = (r.toolCalls ?? [])
    .filter((c) => c.toolName === "post_verdict")
    .map((c) => ({ args: c.args, output: c.output, isError: c.isError }));
  const line = {
    caseId,
    iteration,
    evalId: id,
    model,
    syspromptChars: Number(syspromptChars),
    syspromptSha256: syspromptSha,
    packBV3GateSchema: packBV3 === "true",
    fixturePinSha: fixturePinSha || undefined,
    postVerdict,
    sessionId: r.sessionId,
    durationMs: r.durationMs,
  };
  appendFileSync(auditPath, `${JSON.stringify(line)}\n`);
}
// ponytail: self-check first line written
if (createHash("sha256").update(syspromptSha).digest("hex").length !== 64) {
  process.exit(4);
}
