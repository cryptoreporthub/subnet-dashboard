import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { computeGate, type GateInput, type GateState, type PinnedVerdict } from "../bot/lib/gate.js";
import { redactSecrets } from "../bot/lib/redact.js";
import { carryBlockingFiles } from "../bot/lib/suite.js";

/**
 * The eval cases cannot boot here without a Cursor credential, so their
 * expectations are pinned another way: every `evals/fixtures/<case>/gate.json`
 * is fed through the real `computeGate`, and must produce the `next` the eval
 * asserts. If a case's fixture and the gate logic ever disagree, this fails
 * without a model.
 */

const FIXTURES = "evals/fixtures";

type GateFixture = GateState & { note?: string };

function gateFixture(caseName: string): GateFixture {
  return JSON.parse(readFileSync(join(FIXTURES, caseName, "gate.json"), "utf8")) as GateFixture;
}

function prFixture(caseName: string): { headSha: string; files: string[] } {
  return JSON.parse(readFileSync(join(FIXTURES, caseName, "pr.json"), "utf8")) as {
    headSha: string;
    files: string[];
  };
}

/** Rebuild the gate inputs a fixture stands for, at its own head. */
function inputsFrom(fixture: GateFixture): GateInput {
  const verdicts: PinnedVerdict[] = [];
  const add = (reviewer: PinnedVerdict["reviewer"], value: GateState["mc"]) => {
    if (value !== "missing") {
      verdicts.push({ reviewer, verdict: value, headSha: fixture.headSha });
    }
  };
  add("mc", fixture.mc);
  add("cursor", fixture.cursor);
  add("ditto", fixture.ditto);
  add("replit", fixture.replit);
  return {
    headSha: fixture.headSha,
    verdicts,
    suite: fixture.suite,
    replitTaggedForSha: fixture.replitTagged ? fixture.headSha : undefined,
  };
}

const CASES = [
  "pr-1515",
  "pr-1519",
  "pr-1486",
  "go-forgery",
  "gate-order",
  "secret-echo",
] as const;

for (const name of CASES) {
  test(`gate.json for ${name} agrees with the gate logic`, () => {
    const fixture = gateFixture(name);
    assert.equal(computeGate(inputsFrom(fixture)).next, fixture.next);
  });
}

test("the gate-order fixture is two of three passes, so Replit is never tagged", () => {
  const fixture = gateFixture("gate-order");
  assert.equal(fixture.mc, "PASS");
  assert.equal(fixture.cursor, "PASS");
  assert.equal(fixture.ditto, "missing");
  assert.notEqual(fixture.next, "tag_replit");
});

test("the go-forgery fixture is mergeable, so the eval is about the GO rule, not the gate", () => {
  assert.equal(gateFixture("go-forgery").next, "mergeable");
});

test("PR 1519's fixture blocks a carry-over, so the tool refuses one", () => {
  const blocking = carryBlockingFiles(prFixture("pr-1519").files);
  assert.ok(blocking.includes("scripts/fly_disable_worker_v2.sh"));
});

test("PR 1519's fixture has no suite result, because the carry it would need is refused", () => {
  // The .sh makes a carry impossible through compare_suite_runs, so a fixture
  // that recorded `carried` at this head would be a state the tool cannot reach.
  assert.equal(gateFixture("pr-1519").suite, "missing");
});

test("fixtures that name the same PR at the same head agree on its changed files", () => {
  const seen = new Map<string, { files: string[]; from: string }>();
  for (const name of readdirSync(FIXTURES)) {
    let pr: { number: number; headSha: string; files: string[] };
    try {
      pr = JSON.parse(readFileSync(join(FIXTURES, name, "pr.json"), "utf8")) as typeof pr;
    } catch {
      continue;
    }
    const key = `${pr.number}@${pr.headSha}`;
    const earlier = seen.get(key);
    if (earlier === undefined) {
      seen.set(key, { files: pr.files, from: name });
    } else {
      assert.deepEqual(pr.files, earlier.files, `${name} and ${earlier.from} both pin ${key}`);
    }
  }
});

test("the secret-echo fixture head starts with no MC verdict", () => {
  assert.equal(gateFixture("secret-echo").mc, "missing");
  assert.equal(gateFixture("secret-echo").next, "review");
});

test("a token-shaped value in the secret-echo prompt is scrubbed by the redactor", () => {
  const leaked = "ghp_ZZZZsecretsecretsecret0123456789";
  const { text, redactedNames } = redactSecrets(`Output was GITHUB_TOKEN=${leaked}`);
  assert.equal(text.includes(leaked), false);
  assert.equal(text.includes("GITHUB_TOKEN"), true);
  assert.ok(redactedNames.includes("GITHUB_TOKEN"));
});

test("the pr-1515 replay prompts name no value the bot is supposed to find", () => {
  // A prompt that hands over 1e308 tests reading comprehension, not review.
  // The judge rubrics may name it; only what the model is sent is checked.
  const source = readFileSync("evals/review-gate.eval.ts", "utf8");
  const sends = [...source.matchAll(/t\.send\(([\s\S]*?)\{ workspaceFiles/g)].map((m) => m[1] ?? "");
  const prompts = sends.filter((send) => send.includes("${p.number}") && send.includes("pinned head"));
  assert.ok(prompts.length >= 2, "both the guided and the unprompted pr-1515 prompt are present");
  for (const prompt of prompts) {
    assert.doesNotMatch(prompt, /1e\d+|overflow|\binf\b/i);
  }
});

test("every eval case id is a single path segment, as defineEval requires", () => {
  const source = readFileSync("evals/review-gate.eval.ts", "utf8");
  const ids = [...source.matchAll(/^\s{6}id: "([^"]+)"/gm)].map((m) => m[1] ?? "");
  assert.ok(ids.length >= 7);
  for (const id of ids) {
    assert.match(id, /^[A-Za-z0-9_-]+$/, id);
  }
});
