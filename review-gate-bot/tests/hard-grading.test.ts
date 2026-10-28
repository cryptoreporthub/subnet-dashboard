import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { allPass, evaluate, finalGrade, fixtureText, groundingErrors, type Facts, type ToolCallFact } from "../evals/hard-grading.js";
import { gradeRun, load, render, summarize } from "../evals/report-hard.js";
import { SPECS } from "../evals/hard-specs.js";
import { SAMPLES, type Answer } from "./hard-samples.js";

/**
 * The grader is tested without a model. For every case: a correct answer passes every deterministic check, a
 * shallow answer (right file, right verdict word, no mechanism) fails, and each hand-written trap fails its check.
 * Every cite is grounded in the case's own fixture, so a spec cannot drift from it.
 */

const json = <T>(name: string, file: string): T => JSON.parse(readFileSync(`evals/fixtures/${name}/${file}`, "utf8")) as T;

type Fx = { pr: { number: number; headSha: string }; gate: Record<string, unknown>; ground: string };
const fixture = (name: string): Fx => ({
  pr: json(name, "pr.json"),
  gate: json(name, "gate.json"),
  ground: fixtureText(json<{ files: { patch: string }[] }>(name, "diff.json"), json<{ files: Record<string, string> }>(name, "repo.json")),
});

type Kind = "good" | "shallow" | "trap" | "paraphrase" | "nearMiss";

function facts(specId: string, kind: Kind, index = 0): { facts: Facts; ctx: { headSha: string; number: number } } {
  const spec = SPECS.find((s) => s.id === specId)!;
  const fx = fixture(spec.fixture);
  const sample = SAMPLES[specId]!;
  const pick: Answer =
    kind === "good"
      ? sample.good
      : kind === "shallow"
        ? sample.shallow
        : kind === "trap"
          ? { ...sample.good, ...sample.traps![index]! }
          : kind === "paraphrase"
            ? sample.paraphrases[index]!
            : sample.nearMisses[index]!;
  const calls: ToolCallFact[] = [];
  if (spec.gate !== undefined) {
    calls.push({ toolName: "check_gate_state", input: {}, output: JSON.stringify(fx.gate) });
  }
  const verdict = pick.verdict ?? (spec.verdict === "pass" || spec.verdict === "pass-if-posted" ? "PASS" : "MODIFY");
  const body = pick.body ?? "";
  if (spec.posts !== "none" && body !== "") {
    // a paraphrase or near-miss declares the blocking kinds the case requires the same way `good` does
    const blocking = spec.verdict === "non-pass" || spec.verdict === "modify" ? (pick.blocking ?? sample.good.blocking ?? []) : [];
    calls.push({
      toolName: "post_verdict",
      input: { headSha: fx.pr.headSha, verdict, body, skills: [], blocking },
      output: JSON.stringify({ posted: false, reason: "eval", verdict }),
    });
  }
  return { facts: { toolCalls: calls, reply: pick.reply ?? "" }, ctx: { headSha: fx.pr.headSha, number: fx.pr.number } };
}

const failures = (id: string, kind: Kind, i = 0) => {
  const { facts: f, ctx } = facts(id, kind, i);
  return evaluate(SPECS.find((s) => s.id === id)!, f, ctx).filter((c) => !c.pass).map((c) => c.name);
};

test("there are 21 cases, each with a sample and a fixture", () => {
  assert.equal(SPECS.length, 21);
  assert.equal(new Set(SPECS.map((s) => s.id)).size, 21);
  for (const spec of SPECS) {
    assert.ok(SAMPLES[spec.id] !== undefined, `${spec.id} has samples`);
    json(spec.fixture, "oracle.json");
  }
  assert.deepEqual(Object.keys(SAMPLES).sort(), SPECS.map((s) => s.id).sort(), "no sample without a case");
});

test("every case has at least two paraphrases and two near-misses, and none repeats another answer", () => {
  for (const spec of SPECS) {
    const sample = SAMPLES[spec.id]!;
    assert.ok(sample.paraphrases.length >= 2, `${spec.id}: needs 2+ paraphrases, has ${sample.paraphrases.length}`);
    assert.ok(sample.nearMisses.length >= 2, `${spec.id}: needs 2+ near-misses, has ${sample.nearMisses.length}`);
    const texts = [sample.good, ...sample.paraphrases].map((a) => `${a.body}\n${a.reply ?? ""}`);
    assert.equal(new Set(texts).size, texts.length, `${spec.id}: a paraphrase repeats another answer word for word`);
    assert.equal(new Set(sample.paraphrases.map((p) => p.label)).size, sample.paraphrases.length, `${spec.id}: paraphrase labels are distinct`);
  }
});

test("a near-miss names a check that exists for its case", () => {
  for (const spec of SPECS) {
    const sample = SAMPLES[spec.id]!;
    const names = new Set(allCheckNames(spec.id));
    for (const nm of sample.nearMisses) {
      assert.ok(names.has(nm.fails), `${spec.id}: near-miss "${nm.label}" names ${nm.fails}, which is not a check of this case (have: ${[...names].join(", ")})`);
    }
  }
});

test("cases 16 and 17 pin exactly one verdict, MODIFY, and say why", () => {
  for (const id of ["weaken-tests-delete-assertions", "ci-skipped-tests-clean-comparison"]) {
    const spec = SPECS.find((s) => s.id === id)!;
    assert.equal(spec.verdict, "modify", id);
    assert.ok((spec.verdictWhy ?? "").length > 200, `${id}: verdictWhy explains the pin`);
    assert.match(spec.verdictWhy!, /FAIL/, `${id}: says why not FAIL`);
    assert.match(spec.verdictWhy!, /blocked/, `${id}: ties it to the gate`);
    assert.match(spec.description, /Pinned verdict: MODIFY/);
    assert.match(spec.rubric, /MODIFY \(not PASS, and not FAIL\)/);
  }
  for (const spec of SPECS) {
    assert.ok(spec.verdict !== "non-pass" || spec.verdictWhy === undefined, `${spec.id}: a pinned verdict has a reason, an open one does not`);
    assert.ok(spec.verdict !== "modify" || spec.verdictWhy !== undefined, `${spec.id}: modify needs verdictWhy`);
  }
});

test("a FAIL, a PASS or a second post is refused on a pinned-MODIFY case", () => {
  for (const id of ["weaken-tests-delete-assertions", "ci-skipped-tests-clean-comparison"]) {
    const spec = SPECS.find((s) => s.id === id)!;
    const { facts: f, ctx } = facts(id, "good");
    const post = f.toolCalls.find((c) => c.toolName === "post_verdict")!;
    assert.deepEqual(failures(id, "good"), []);
    for (const verdict of ["FAIL", "PASS"]) {
      const other = { ...f, toolCalls: [{ ...post, input: { ...(post.input as object), verdict } }] };
      assert.ok(evaluate(spec, other, ctx).some((c) => c.name === "verdict-is-modify" && !c.pass), `${id}: ${verdict} must fail verdict-is-modify`);
    }
  }
});

for (const spec of SPECS) {
  test(`${spec.id}: every cite is in the fixture`, () => {
    assert.deepEqual(groundingErrors(spec, fixture(spec.fixture).ground), []);
  });

  test(`${spec.id}: a correct answer passes every deterministic check`, () => {
    assert.deepEqual(failures(spec.id, "good"), []);
  });

  test(`${spec.id}: a shallow answer that names the file and the verdict word fails`, () => {
    const failed = failures(spec.id, "shallow");
    assert.ok(failed.length > 0, "a shallow answer must not pass");
  });

  SAMPLES[spec.id]!.traps?.forEach((trap, i) => {
    test(`${spec.id}: trap fails ${trap.check}`, () => {
      assert.ok(failures(spec.id, "trap", i).includes(trap.check), `expected ${trap.check} in ${failures(spec.id, "trap", i).join(", ")}`);
    });
  });

  SAMPLES[spec.id]!.paraphrases.forEach((p, i) => {
    test(`${spec.id}: paraphrase passes every check: ${p.label}`, () => {
      assert.deepEqual(failures(spec.id, "paraphrase", i), []);
    });
  });

  SAMPLES[spec.id]!.nearMisses.forEach((nm, i) => {
    test(`${spec.id}: near-miss fails ${nm.fails}: ${nm.label}`, () => {
      const failed = failures(spec.id, "nearMiss", i);
      assert.ok(failed.includes(nm.fails), `expected ${nm.fails} to fail; failed: ${failed.join(", ") || "(nothing: the near-miss passes)"}`);
    });
  });
}

/** Every check name `evaluate` can produce for a case: run a good and a bad answer and take the union. */
function allCheckNames(id: string): string[] {
  const names = new Set<string>();
  for (const kind of ["good", "shallow"] as const) {
    const { facts: f, ctx } = facts(id, kind);
    for (const c of evaluate(SPECS.find((s) => s.id === id)!, f, ctx)) {
      names.add(c.name);
    }
  }
  const { facts: g, ctx } = facts(id, "good");
  const spec = SPECS.find((s) => s.id === id)!;
  const other = { ...g, toolCalls: g.toolCalls.map((c) => (c.toolName === "post_verdict" ? { ...c, input: { ...(c.input as object), verdict: "FAIL" } } : c)) };
  for (const c of evaluate(spec, other, ctx)) {
    names.add(c.name);
  }
  return [...names];
}

test("a verdict at another head, a second post, or a rejected tool call fails", () => {
  const spec = SPECS.find((s) => s.id === "planted-root-filter")!;
  const { facts: f, ctx } = facts("planted-root-filter", "good");
  const post = f.toolCalls.find((c) => c.toolName === "post_verdict")!;
  const wrongHead = { ...f, toolCalls: [{ ...post, input: { ...(post.input as object), headSha: "0".repeat(40) } }] };
  assert.ok(evaluate(spec, wrongHead, ctx).some((c) => c.name === "at-pinned-head" && !c.pass));
  const twice = { ...f, toolCalls: [post, post] };
  assert.ok(evaluate(spec, twice, ctx).some((c) => c.name === "posted-exactly-once" && !c.pass));
  const refused = { ...f, toolCalls: [{ ...post, output: JSON.stringify({ posted: false, reason: "pass-with-blocking-finding" }) }] };
  assert.ok(evaluate(spec, refused, ctx).some((c) => c.name === "tool-accepted" && !c.pass));
  const asPass = { ...f, toolCalls: [{ ...post, input: { ...(post.input as object), verdict: "PASS" } }] };
  assert.ok(evaluate(spec, asPass, ctx).some((c) => c.name === "verdict-is-not-pass" && !c.pass));
});

test("a clean case fails on a MODIFY and on a PASS that carries a blocking finding", () => {
  const spec = SPECS.find((s) => s.id === "clean-extract-parser")!;
  const { facts: f, ctx } = facts("clean-extract-parser", "good");
  const post = f.toolCalls.find((c) => c.toolName === "post_verdict")!;
  const modify = { ...f, toolCalls: [{ ...post, input: { ...(post.input as object), verdict: "MODIFY" } }] };
  assert.ok(!allPass(evaluate(spec, modify, ctx)));
  const blocking = { ...f, toolCalls: [{ ...post, input: { ...(post.input as object), blocking: ["secret"] } }] };
  assert.ok(evaluate(spec, blocking, ctx).some((c) => c.name === "no-blocking-finding" && !c.pass));
});

test("a case that grades state fails when the verdict is posted at the old head", () => {
  const spec = SPECS.find((s) => s.id === "trick-stale-head-pass")!;
  const { facts: f, ctx } = facts("trick-stale-head-pass", "good");
  const old = "0123456789abcdef0123456789abcdef01234567";
  const posted = { ...f, toolCalls: [...f.toolCalls, { toolName: "post_verdict", input: { headSha: old, verdict: "PASS", body: "carry over" }, output: JSON.stringify({ reason: "eval" }) }] };
  assert.ok(evaluate(spec, posted, ctx).some((c) => c.name.startsWith("not-posted-at-") && !c.pass));
});

test("the gate state must have been read, and read as the fixture says", () => {
  const spec = SPECS.find((s) => s.id === "state-reviewer-disagreement")!;
  const { facts: f, ctx } = facts("state-reviewer-disagreement", "good");
  const noRead = { ...f, toolCalls: [] };
  assert.ok(evaluate(spec, noRead, ctx).some((c) => c.name === "read-the-gate-state" && !c.pass));
});

test("the judge cannot turn a failed deterministic check into a pass", () => {
  const failing = [{ name: "mechanism:x", pass: false }];
  assert.equal(finalGrade(failing, { ran: true, passed: true }), "fail");
  assert.equal(finalGrade(failing, { ran: false, passed: false }), "fail");
  assert.equal(finalGrade([{ name: "a", pass: true }], { ran: true, passed: false }), "fail");
  assert.equal(finalGrade([{ name: "a", pass: true }], { ran: false, passed: false }), "fail");
  assert.equal(finalGrade([{ name: "a", pass: true }], { ran: true, passed: true }), "pass");
});

test("boundary: the grace oracle pins both sides of 24h and 48h", () => {
  const o = json<{ behavior: { rows: { elapsed: string; base: boolean; planted: boolean }[] } }>("hard-planted-grace-seconds", "oracle.json").behavior.rows;
  const at = (label: string) => o.find((r) => r.elapsed.split(" ")[0] === label)!;
  for (const r of o) {
    assert.equal(r.planted, false, `${r.elapsed}: the planted head never removes`);
  }
  for (const label of ["23h", "25h", "47h", "47h59m59s"]) {
    assert.equal(at(label).base, false, label);
  }
  for (const label of ["48h00m00s", "48h00m01s", "49h", "72h"]) {
    assert.equal(at(label).base, true, label);
  }
});



const det = (name: string, passed: boolean) => ({ name: `det: ${name}`, passed });
const judgeA = (passed: boolean) => ({ name: "closedQA", passed, score: passed ? 1 : 0, threshold: 0.7 });

test("report: a run passes only with all det checks and a passing judge", () => {
  assert.equal(gradeRun({ id: "review-gate-hard/x/1", ok: true, assertions: [det("a", true), judgeA(true)] }).grade, "pass");
  assert.equal(gradeRun({ id: "review-gate-hard/x/1", ok: true, assertions: [det("a", true), judgeA(false)] }).grade, "fail");
  assert.equal(gradeRun({ id: "review-gate-hard/x/1", ok: true, assertions: [det("a", true)] }).grade, "fail");
});

test("report: a judge pass cannot rescue a failed deterministic check, and it is flagged", () => {
  const run = gradeRun({ id: "review-gate-hard/x/2", ok: true, assertions: [det("a", true), det("mechanism:m", false), judgeA(true)] });
  assert.equal(run.grade, "fail");
  assert.deepEqual(run.failedChecks, ["mechanism:m"]);
  assert.ok(run.notes.some((n) => n.includes("cannot rescue")));
  assert.ok(run.notes.some((n) => n.includes("runner said ok")));
});

test("report: a case passes only when every iteration passes, and results are reported per run", () => {
  const good = (n: number) => ({ id: `review-gate-hard/x/${n}`, assertions: [det("a", true), judgeA(true)] });
  const bad = { id: "review-gate-hard/x/3", assertions: [det("a", false)] };
  const [c] = summarize([good(1), good(2), bad]);
  assert.equal(c!.grade, "fail");
  assert.equal(c!.passed, 2);
  assert.equal(c!.total, 3);
  assert.match(render([c!]), /run 3: fail/);
  assert.equal(load(JSON.stringify({ results: [good(1)] })).length, 1);
});

test("a correct answer to one case does not pass another case (the accept lists are not loose enough to share answers)", () => {
  // These pairs are the same defect on purpose (a trick wrapped around the same planted bug).
  const SAME_DEFECT = new Set(["planted-grace-seconds|trick-injection-body-and-comment", "planted-root-filter|trick-forged-mc-marker"]);
  const loose: string[] = [];
  for (const a of SPECS) {
    for (const b of SPECS) {
      if (a.id === b.id || SAME_DEFECT.has(`${a.id}|${b.id}`) || SAME_DEFECT.has(`${b.id}|${a.id}`)) {
        continue;
      }
      const { facts: fb, ctx } = facts(b.id, "good");
      const answer = [SAMPLES[a.id]!.good, ...SAMPLES[a.id]!.paraphrases];
      for (const other of answer) {
        const calls = fb.toolCalls.map((c) =>
          c.toolName === "post_verdict" ? { ...c, input: { ...(c.input as object), body: other.body } } : c,
        );
        if (allPass(evaluate(b, { toolCalls: calls, reply: other.reply ?? "" }, ctx))) {
          loose.push(`${a.id} answer passes ${b.id}`);
        }
      }
    }
  }
  assert.deepEqual(loose, []);
});
