import assert from "node:assert/strict";
import test from "node:test";
import {
  computeGate,
  cursorDittoTagKey,
  replitAskKey,
  replitTagKey,
  verdictAt,
  type GateInput,
  type PinnedVerdict,
} from "../bot/lib/gate.js";

const HEAD = "a".repeat(40);
const OTHER = "b".repeat(40);

function input(overrides: Partial<GateInput> = {}): GateInput {
  return { headSha: HEAD, verdicts: [], suite: "missing", ...overrides };
}

function v(
  reviewer: PinnedVerdict["reviewer"],
  verdict: PinnedVerdict["verdict"],
  headSha = HEAD,
): PinnedVerdict {
  return { reviewer, verdict, headSha };
}

test("a head with no MC verdict asks for the review", () => {
  assert.equal(computeGate(input()).next, "review");
});

test("MC PASS alone waits for Cursor and Ditto, never tags Replit", () => {
  const gate = computeGate(input({ verdicts: [v("mc", "PASS")] }));
  assert.equal(gate.next, "await_cursor_ditto");
  assert.notEqual(gate.next, "tag_replit");
});

test("two of three formal passes never reach tag_replit", () => {
  const gate = computeGate(input({ verdicts: [v("mc", "PASS"), v("cursor", "PASS")] }));
  assert.equal(gate.next, "await_cursor_ditto");
});

test("three passes with no suite result must run the suite", () => {
  const gate = computeGate(
    input({ verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")] }),
  );
  assert.equal(gate.next, "run_suite");
});

test("three passes and a regressed suite does not tag Replit", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "regressed",
    }),
  );
  assert.equal(gate.next, "run_suite");
});

test("three passes and a clean suite tags Replit exactly once", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "clean",
    }),
  );
  assert.equal(gate.next, "tag_replit");
});

test("a carried suite counts as clean for the gate", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "carried",
    }),
  );
  assert.equal(gate.next, "tag_replit");
});

test("after the Replit tag the gate waits for the Replit verdict", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "clean",
      replitTaggedForSha: HEAD,
    }),
  );
  assert.equal(gate.next, "await_replit");
});

test("Replit PASS at the same head makes the PR mergeable", () => {
  const gate = computeGate(
    input({
      verdicts: [
        v("mc", "PASS"),
        v("cursor", "PASS"),
        v("ditto", "PASS"),
        v("replit", "PASS"),
      ],
      suite: "clean",
      replitTaggedForSha: HEAD,
    }),
  );
  assert.equal(gate.next, "mergeable");
});

test("a Replit tag recorded against another head does not count", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "clean",
      replitTaggedForSha: OTHER,
    }),
  );
  assert.equal(gate.next, "tag_replit");
  assert.equal(gate.replitTagged, false);
});

test("a new head resets every verdict", () => {
  const stale: PinnedVerdict[] = [
    v("mc", "PASS", OTHER),
    v("cursor", "PASS", OTHER),
    v("ditto", "PASS", OTHER),
    v("replit", "PASS", OTHER),
  ];
  const gate = computeGate({ headSha: HEAD, verdicts: stale, suite: "clean" });
  assert.equal(gate.mc, "missing");
  assert.equal(gate.cursor, "missing");
  assert.equal(gate.ditto, "missing");
  assert.equal(gate.replit, "missing");
  assert.equal(gate.next, "review");
});

test("any FAIL blocks, whatever else passed", () => {
  const gate = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "FAIL")],
      suite: "clean",
    }),
  );
  assert.equal(gate.next, "blocked");
});

test("MODIFY from a reviewer holds the gate at the awaiting step, not blocked", () => {
  const gate = computeGate(input({ verdicts: [v("mc", "PASS"), v("cursor", "MODIFY")] }));
  assert.equal(gate.next, "await_cursor_ditto");
});

test("the latest verdict at a head wins", () => {
  const verdicts = [v("cursor", "MODIFY"), v("cursor", "PASS")];
  assert.equal(verdictAt(verdicts, "cursor", HEAD), "PASS");
});

test("verdictAt ignores another reviewer and another head", () => {
  const verdicts = [v("ditto", "PASS"), v("cursor", "PASS", OTHER)];
  assert.equal(verdictAt(verdicts, "cursor", HEAD), "missing");
});

test("tag and ask keys are distinct per slot and per head", () => {
  assert.notEqual(cursorDittoTagKey(1515, HEAD), replitTagKey(1515, HEAD));
  assert.notEqual(replitTagKey(1515, HEAD), replitAskKey(1515, HEAD));
  assert.notEqual(cursorDittoTagKey(1515, HEAD), cursorDittoTagKey(1515, OTHER));
  assert.notEqual(cursorDittoTagKey(1515, HEAD), cursorDittoTagKey(1516, HEAD));
});
