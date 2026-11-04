#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";

const [aggPath, slotPath, evalId] = process.argv.slice(2);
if (!aggPath || !slotPath || !evalId) {
  console.error("usage: merge-slot-into-wave-json.mjs <aggregate.json> <slot.json> <evalId>");
  process.exit(2);
}
const agg = JSON.parse(readFileSync(aggPath, "utf8"));
const slot = JSON.parse(readFileSync(slotPath, "utf8"));
const row = slot.results?.[0];
if (!row) {
  console.error("STOP: slot json missing results[0]");
  process.exit(3);
}
row.id = evalId;
agg.results = agg.results ?? [];
agg.results.push(row);
writeFileSync(aggPath, `${JSON.stringify(agg, null, 2)}\n`);
