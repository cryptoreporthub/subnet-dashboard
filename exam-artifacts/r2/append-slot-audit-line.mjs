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
const planIdx = flag("--plan-idx");
const retryOfIdx = flag("--retry-of-idx");
const attempt = flag("--attempt");
const slotKilled = flag("--slot-killed") === "true";
const killReason = flag("--kill-reason");
const slotStartedAt = flag("--slot-started-at");
const slotEndedAt = flag("--slot-ended-at");
const timedOut = flag("--timed-out") === "true";
const slotFailed = flag("--slot-failed") === "true";
const slotFailedReason = flag("--slot-failed-reason");
const slotJson = flag("--slot-json");

if (!auditPath || !evalId || !caseId || !iteration || !slotStartedAt || !slotEndedAt) {
  console.error("missing required audit args");
  process.exit(2);
}
if (!syspromptSha || syspromptSha.length !== 64) {
  console.error("STOP V1: invalid sysprompt sha");
  process.exit(3);
}

function countReadRepoFileCommitEnumErrors(toolCalls) {
  const needle = 'Invalid option: expected one of "head"|"base"';
  return (toolCalls ?? []).filter(
    (c) =>
      c.toolName === "read_repo_file" &&
      (String(c.output ?? "").includes(needle) || (c.isError && String(c.output ?? "").includes("Invalid option"))),
  ).length;
}

const model = JSON.parse(modelJson ?? "{}");
let postVerdict = [];
let sessionId;
let durationMs;
let readRepoFileCommitEnumErrors = 0;
if (slotJson && !timedOut) {
  const slotDoc = JSON.parse(readFileSync(slotJson, "utf8"));
  const row = slotDoc.results?.[0];
  if (!row && !slotFailed) {
    console.error("STOP: slot json missing results[0]");
    process.exit(4);
  }
  if (row) {
    readRepoFileCommitEnumErrors = countReadRepoFileCommitEnumErrors(row.toolCalls);
    if (!slotFailed) {
      postVerdict = (row.toolCalls ?? [])
        .filter((c) => c.toolName === "post_verdict")
        .map((c) => ({ args: c.args, output: c.output, isError: c.isError }));
      sessionId = row.sessionId;
      durationMs = row.durationMs;
    } else {
      sessionId = row.sessionId;
      durationMs = row.durationMs;
    }
  }
}
const v2Outcome =
  timedOut || slotFailed || postVerdict.length === 0 ? "NO_POST" : "POST";
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
  postVerdict: timedOut || slotFailed ? [] : postVerdict,
  sessionId,
  durationMs,
};
if (planIdx !== undefined) {
  line.planIdx = Number(planIdx);
}
if (retryOfIdx !== undefined) {
  line.retryOfIdx = Number(retryOfIdx);
}
if (attempt !== undefined) {
  line.attempt = Number(attempt);
}
if (slotKilled) {
  line.slotKilled = true;
  line.killReason = killReason || "runner_lost_in_flight";
  line.backfilled = true;
}
if (readRepoFileCommitEnumErrors > 0) {
  line.readRepoFileCommitEnumErrors = readRepoFileCommitEnumErrors;
}
if (timedOut) {
  line.slotTimedOut = true;
}
if (slotFailed) {
  line.slotFailed = true;
  line.slotFailedReason = slotFailedReason || "eval_exit_nonzero";
}
appendFileSync(auditPath, `${JSON.stringify(line)}\n`);
