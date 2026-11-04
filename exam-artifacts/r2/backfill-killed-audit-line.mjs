#!/usr/bin/env node
/** Insert backfilled audit line(s) into ndjson (does not append at EOF if --insert-before-eval). */
import { readFileSync, writeFileSync } from "node:fs";

const auditPath = process.argv[2];
const insertJson = process.argv[3];
const beforeEvalId = process.argv[4];
const markEvalId = process.argv[5];
const markPatchJson = process.argv[6];

if (!auditPath || !insertJson) {
  console.error("usage: backfill-killed-audit-line.mjs <audit.ndjson> <insertLineJson> [beforeEvalId] [markEvalId] [markPatchJson]");
  process.exit(2);
}

const lines = readFileSync(auditPath, "utf8").trimEnd().split("\n").filter(Boolean);
const insert = JSON.parse(insertJson);
const out = [];
let inserted = false;
for (const line of lines) {
  const o = JSON.parse(line);
  if (!inserted && beforeEvalId && o.evalId === beforeEvalId && o.slotStartedAt === "2026-11-04T14:45:15Z") {
    out.push(JSON.stringify(insert));
    inserted = true;
  }
  if (markEvalId && markPatchJson && o.evalId === markEvalId && o.slotStartedAt === "2026-11-04T14:45:15Z") {
    Object.assign(o, JSON.parse(markPatchJson));
  }
  out.push(JSON.stringify(o));
}
if (!inserted && beforeEvalId) {
  console.error("STOP: insert anchor not found");
  process.exit(3);
}
writeFileSync(auditPath, `${out.join("\n")}\n`);
