#!/usr/bin/env node
/** Append one slot audit line (live eval or slot_timeout). V2: capped slot => v2Outcome NO_POST. */
import { appendFileSync, readFileSync } from "node:fs";

const args = process.argv.slice(2);
function flag(name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
}
const auditPath = flag("--audit");
const syspromptChars = flag("--sysprompt-chars");
const syspromptSha = flag("--sysprompt-sha");
const modelJson = flag("--model-json");
const fixturePinSha = flag("--fixture-pin");
const packBV3 = flag("--pack-b-v3") === "true";
const evalId = flag("--eval-id");
const caseId = flag("--case-id");
const iteration = flag("--iteration");
const slotStartedAt = flag("--slot-started-at");
const slotEndedAt = flag("--slot-ended-at");
const timedOut = flag("--timed-out") === "true";
const slotJson = flag("--slot-json");

if (!auditPath || !evalId || !caseId || !iteration || !slotStartedAt || !slotEndedAt) {
  console.error("usage: append-slot-audit-line.mjs --audit ... --eval-id ... --case-id ... --iteration ... --slot-started-at ISO --slot-ended-at ISO [--timed-out true] [--slot-json path]");
  process.exit(2);
}
if (!syspromptSha || syspromptSha.length !== 64) {
  console.error("STOP: invalid sysprompt sha");
  process.exit(3);
}
const model = JSON.parse(modelJson ?? "{}");
let postVerdict = [];
let sessionId;
let durationMs;
if (!timedOut && slotJson) {
  const slotDoc = JSON.parse(readFileSync(slotJson, "utf8"));
  const row = slotDoc.results?.[0];
  if (!row) {
    console.error("STOP: slot json missing results[0]");
    process.exit(4);
  }
  postVerdict = (row.toolCalls ?? [])
    .filter((c) => c.toolName === "post_verdict")
    .map((c) => ({ args: c.args, output: c.output, isError: c.isError }));
  sessionId = row.sessionId;
  durationMs = row.durationMs;
}
const v2Outcome = timedOut || postVerdict.length === 0 ? "NO_POST" : "POST";
const line = {
  caseId,
  iteration,
  evalId,
  model,
  syspromptChars: Number(syspromptChars),
  syspromptSha256: syspromptSha,
  packBV3GateSchema: packBV3,
  fixturePinSha: fixturePinSha || undefined,
  slotStartedAt,
  slotEndedAt,
  v2Outcome,
  postVerdict: timedOut ? [] : postVerdict,
  sessionId,
  durationMs,
};
if (timedOut) {
  line.slotTimedOut = true;
}
appendFileSync(auditPath, `${JSON.stringify(line)}\n`);
