#!/usr/bin/env node
/** Append one R2 slot audit line (V1 sysprompt, V2 no-post, slot times). */
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
const evalId = flag("--eval-id");
const caseId = flag("--case-id");
const iteration = flag("--iteration");
const condition = flag("--condition");
const role = flag("--role");
const botCheckoutSha = flag("--bot-checkout-sha");
const r2MethodArm = flag("--r2-method-arm");
const slotStartedAt = flag("--slot-started-at");
const slotEndedAt = flag("--slot-ended-at");
const timedOut = flag("--timed-out") === "true";
const slotJson = flag("--slot-json");

if (!auditPath || !evalId || !caseId || !iteration || !slotStartedAt || !slotEndedAt) {
  console.error("missing required audit args");
  process.exit(2);
}
if (!syspromptSha || syspromptSha.length !== 64) {
  console.error("STOP V1: invalid sysprompt sha");
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
  condition,
  role,
  botCheckoutSha,
  r2MethodArm,
  model,
  syspromptChars: Number(syspromptChars),
  syspromptSha256: syspromptSha,
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
