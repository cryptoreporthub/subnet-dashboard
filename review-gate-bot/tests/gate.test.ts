import assert from "node:assert/strict";
import test from "node:test";
import { suiteKey } from "../bot/lib/gh.js";
import {
  computeGate,
  cursorDittoTagKey,
  gateActions,
  needsReviewTurn,
  prKey,
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

test("tag, ask and suite keys are distinct per slot and per head", () => {
  const pr = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1515 };
  assert.notEqual(cursorDittoTagKey(pr, HEAD), replitTagKey(pr, HEAD));
  assert.notEqual(replitTagKey(pr, HEAD), replitAskKey(pr, HEAD));
  assert.notEqual(cursorDittoTagKey(pr, HEAD), cursorDittoTagKey(pr, OTHER));
  assert.notEqual(cursorDittoTagKey(pr, HEAD), cursorDittoTagKey({ ...pr, number: 1516 }, HEAD));
  assert.notEqual(suiteKey(pr, HEAD), suiteKey(pr, OTHER));
});

test("the same PR number in another repository has its own tag, ask and suite keys", () => {
  const pr = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1515 };
  const other = { ...pr, owner: "someone-else" };
  assert.notEqual(cursorDittoTagKey(pr, HEAD), cursorDittoTagKey(other, HEAD));
  assert.notEqual(replitTagKey(pr, HEAD), replitTagKey(other, HEAD));
  assert.notEqual(replitAskKey(pr, HEAD), replitAskKey(other, HEAD));
  assert.notEqual(suiteKey(pr, HEAD), suiteKey(other, HEAD));
});

test("a PR's key tells two repositories' PR 1522 apart and is stable for one PR", () => {
  const ours = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
  const other = { owner: "someone-else", repo: "subnet-dashboard", number: 1522 };
  assert.notEqual(prKey(ours), prKey(other));
  assert.equal(prKey(ours), prKey({ ...ours }));
});

// --- Finding 8: the draft guard, for every delivery ----------------------

test("a draft is never tagged, asked about or reviewed, at any gate state", () => {
  const states = [
    input(),
    input({ verdicts: [v("mc", "PASS")] }),
    input({ verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")], suite: "clean" }),
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "clean",
      replitTaggedForSha: HEAD,
    }),
    input({ verdicts: [v("cursor", "FAIL")] }),
  ];
  for (const gateInput of states) {
    const state = computeGate(gateInput);
    const actions = gateActions(state, true);
    assert.equal(actions.draft, true);
    assert.equal(actions.tagCursorDitto, false, `draft tagged at ${state.next}`);
    assert.equal(actions.tagReplit, false);
    assert.equal(actions.askReplit, false);
    assert.equal(actions.needsReviewTurn, false, `draft reviewed at ${state.next}`);
  }
});

test("a non-draft is tagged and asked exactly as the gate allows", () => {
  const tagReplitState = computeGate(
    input({ verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")], suite: "clean" }),
  );
  const atTag = gateActions(tagReplitState, false);
  assert.equal(atTag.tagCursorDitto, true);
  assert.equal(atTag.tagReplit, true);
  assert.equal(atTag.askReplit, true);

  const awaitReplitState = computeGate(
    input({
      verdicts: [v("mc", "PASS"), v("cursor", "PASS"), v("ditto", "PASS")],
      suite: "clean",
      replitTaggedForSha: HEAD,
    }),
  );
  const atAwait = gateActions(awaitReplitState, false);
  assert.equal(atAwait.tagReplit, false, "the tag is not posted twice");
  assert.equal(atAwait.askReplit, true, "a failed ask is retried from await_replit");
});

test("a blocked gate posts no tag", () => {
  const actions = gateActions(computeGate(input({ verdicts: [v("cursor", "FAIL")] })), false);
  assert.equal(actions.tagCursorDitto, false);
  assert.equal(actions.tagReplit, false);
  assert.equal(actions.askReplit, false);
});

test("a model turn is spent only when MC has no verdict at this head", () => {
  assert.equal(needsReviewTurn(computeGate(input())), true, "no MC verdict: review it");
  assert.equal(
    needsReviewTurn(computeGate(input({ verdicts: [v("mc", "PASS")] }))),
    false,
    "MC already passed: the gate is waiting on the others, not on MC",
  );
  assert.equal(
    needsReviewTurn(computeGate(input({ verdicts: [v("mc", "MODIFY")] }))),
    false,
    "MC already said MODIFY: post_verdict is at-most-once, so a second review posts nothing",
  );
});
