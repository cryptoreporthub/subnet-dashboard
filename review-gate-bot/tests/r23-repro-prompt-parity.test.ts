import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { capture_eval_system_prompt } from "../evals/capture-eval-system-prompt.js";

const MARKER = "reduces what the recorded full-suite comparison actually checks";
const RULE_ONCE =
  "If a change reduces what the recorded full-suite comparison actually checks, the verdict is MODIFY.";

const ROOT = new URL("..", import.meta.url).pathname;

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function countMarker(text: string): number {
  let n = 0;
  let i = 0;
  while ((i = text.indexOf(MARKER, i)) !== -1) {
    n += 1;
    i += MARKER.length;
  }
  return n;
}

function countRuleOnce(text: string): number {
  let n = 0;
  let i = 0;
  while ((i = text.indexOf(RULE_ONCE, i)) !== -1) {
    n += 1;
    i += RULE_ONCE.length;
  }
  return n;
}

/** Sanity: PRE must not contain MARKER. */
test("sanity PRE — MARKER absent", async () => {
  const dump = await capture_eval_system_prompt(ROOT);
  assert.equal(countMarker(dump), 0, "MARKER must be absent on PRE");
});

/** Target group — must FAIL on PRE (marker missing). */
test("target — MARKER present count==1", async () => {
  const dump = await capture_eval_system_prompt(ROOT);
  assert.equal(countMarker(dump), 1, "MARKER count must be 1");
});

test("target — §1a rule appears once", async () => {
  const dump = await capture_eval_system_prompt(ROOT);
  assert.equal(countRuleOnce(dump), 1, "§1a rule sentence must appear once");
});

test("target — dump hash logged for parity", async () => {
  const dump = await capture_eval_system_prompt(ROOT);
  assert.ok(dump.length > 100);
  assert.ok(sha256(dump).length === 64);
});
