#!/usr/bin/env node
/** Append per-slot audit lines from raw agent-sdk eval JSON (no scoring). */
import { createHash } from "node:crypto";
import { readFileSync, appendFileSync } from "node:fs";

const [jsonPath, auditPath, syspromptChars, syspromptSha, modelJson] = process.argv.slice(2);
if (!jsonPath || !auditPath) {
  console.error("usage: extract-slot-audit.mjs <eval.json> <audit.ndjson> <chars> <sha> <modelJson>");
  process.exit(2);
}
const doc = JSON.parse(readFileSync(jsonPath, "utf8"));
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
    model: JSON.parse(modelJson),
    syspromptChars: Number(syspromptChars),
    syspromptSha256: syspromptSha,
    postVerdict,
    sessionId: r.sessionId,
    durationMs: r.durationMs,
  };
  appendFileSync(auditPath, `${JSON.stringify(line)}\n`);
}
