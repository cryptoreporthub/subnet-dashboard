#!/usr/bin/env node
/** Merge one agent-sdk eval JSON (single case) into wave aggregate results[]. */
import { readFileSync, writeFileSync } from "node:fs";

const [wavePath, slotPath, evalId] = process.argv.slice(2);
if (!wavePath || !slotPath || !evalId) {
  console.error("usage: merge-slot-into-wave-json.mjs <wave.json> <slot.json> <evalId>");
  process.exit(2);
}
let wave = { results: [] };
try {
  wave = JSON.parse(readFileSync(wavePath, "utf8"));
} catch {
  wave = { results: [] };
}
if (!Array.isArray(wave.results)) wave.results = [];
wave.results = wave.results.filter((r) => r.id !== evalId);
const slotDoc = JSON.parse(readFileSync(slotPath, "utf8"));
const row = slotDoc.results?.[0];
if (!row) {
  console.error("STOP: slot json missing results[0]");
  process.exit(3);
}
wave.results.push(row);
writeFileSync(wavePath, `${JSON.stringify(wave, null, 2)}\n`);
