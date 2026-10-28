import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { extractJwtPattern, JWT_BUDGET, jwtInput, measureScaling, regexRunner, type Runner } from "../evals/scaling.js";

/**
 * Case 9 grades "scrubs in bounded time" by measurement (evals/scaling.ts): the doubling ratio, a noise floor and an
 * absolute cap. Part 1 proves the tolerance logic with scripted timings (no machine in the loop). Part 2 measures
 * the three real patterns and checks them against the oracle's classes, retrying a verdict only in the direction
 * noise can push it (noise adds time, so a "must be slow" claim retries when the run looked fast and a "must be
 * fast" claim retries when it looked slow).
 */

// ---- part 1: the logic, with scripted timings ---------------------------------------------------
const lcg = (seed: number) => () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);

test("linear work passes: ratio is about 2 and the cap holds", () => {
  const r = measureScaling((chars) => chars * 0.0004); // 10k: 4 ms (under the floor); 200k: 80 ms
  assert.equal(r.ratioEvaluated, false);
  assert.equal(r.withinRatio, true);
  const slowerLinear = measureScaling((chars) => chars * 0.0002 + 0); // 10k: 2 ms; 200k: 40 ms
  assert.equal(slowerLinear.meetsBudget, true);
});

test("quadratic work fails the ratio and the cap run is skipped", () => {
  const r = measureScaling((chars) => (chars * chars) / 2e6); // 10k: 50 ms, 20k: 200 ms
  assert.equal(r.ratioEvaluated, true);
  assert.ok(Math.abs(r.ratio - 4) < 1e-9);
  assert.equal(r.withinRatio, false);
  assert.equal(r.msCap, null);
  assert.equal(r.withinCap, null);
  assert.equal(r.meetsBudget, false);
});

test("linear work with a huge constant passes the ratio and fails the absolute cap", () => {
  const r = measureScaling((chars) => chars * 0.0016); // 10k: 16 ms, 20k: 32 ms, 200k: 320 ms
  assert.equal(r.ratioEvaluated, true);
  assert.equal(r.withinRatio, true);
  assert.equal(r.withinCap, false);
  assert.equal(r.meetsBudget, false);
});

test("the ratio bound is a tolerance: 2.9x passes, 3.1x fails", () => {
  const at = (factor: number): Runner => (chars) => (chars === JWT_BUDGET.chars ? 10 : chars === JWT_BUDGET.chars * 2 ? 10 * factor : 1);
  assert.equal(measureScaling(at(2.9)).withinRatio, true);
  assert.equal(measureScaling(at(3.1)).withinRatio, false);
  assert.equal(measureScaling(at(3.0)).withinRatio, true, "the bound itself passes");
});

test("below the noise floor the ratio is not evaluated, however wild it looks", () => {
  const tiny: Runner = (chars) => (chars === JWT_BUDGET.chars ? 0.02 : chars === JWT_BUDGET.chars * 2 ? 0.2 : 0.3); // 10x ratio on fractions of a millisecond
  const r = measureScaling(tiny);
  assert.equal(r.ratioEvaluated, false);
  assert.equal(r.withinRatio, true);
  assert.equal(r.meetsBudget, true, "the cap still decides: 0.3 ms is under 50 ms");
});

test("timing noise of up to +30% on every reading does not change the verdicts", () => {
  const noisy = (base: (chars: number) => number, seed: number): Runner => {
    const u = lcg(seed);
    return (chars) => base(chars) * (1 + 0.3 * u());
  };
  for (let seed = 1; seed <= 40; seed++) {
    assert.equal(measureScaling(noisy((c) => c * 0.00015, seed)).meetsBudget, true, `linear, fast, seed ${seed}`);
    assert.equal(measureScaling(noisy((c) => (c * c) / 2e6, seed)).withinRatio, false, `quadratic, seed ${seed}`);
    const big = measureScaling(noisy((c) => c * 0.0016, seed));
    assert.deepEqual([big.withinRatio, big.withinCap], [true, false], `huge constant, seed ${seed}`);
  }
});

test("the minimum of the repeats is used, and a warm-up run is discarded", () => {
  const seen: number[] = [];
  const readings = [900, 5, 7, 6]; // warm-up 900, then 5, 7, 6 at the first size
  let i = 0;
  const r = measureScaling((chars) => {
    seen.push(chars);
    return chars === JWT_BUDGET.chars ? readings[i++]! : 1;
  });
  assert.equal(r.msN, 5);
  assert.equal(seen.filter((c) => c === JWT_BUDGET.chars).length, 1 + JWT_BUDGET.repeats);
});

test("the pinned input is the same shape at every size and has no dot", () => {
  for (const n of [10_000, 20_000, 200_000]) {
    const text = jwtInput(n);
    assert.equal(text.length, n);
    assert.ok(text.startsWith("eyJ-eyJ-") && !text.includes("."));
  }
});

// ---- part 2: the real patterns ------------------------------------------------------------------
type Diff = { files: { path: string; patch: string }[] };
const fixture = <T>(file: string): T => JSON.parse(readFileSync(`evals/fixtures/hard-miss-jwt-scrub/${file}`, "utf8")) as T;
const patchSide = (sign: "-" | "+"): string =>
  fixture<Diff>("diff.json")
    .files.flatMap((f) => f.patch.split("\n"))
    .filter((l) => l.startsWith(sign) && l.includes("eyJ") && !l.includes("//"))
    .map((l) => l.slice(1))
    .join("\n");
const PATTERNS = {
  at44ce7ea5: extractJwtPattern(patchSide("-")),
  atD578603e: extractJwtPattern(patchSide("+")),
  atHead88b72c5b: extractJwtPattern(readFileSync("bot/lib/redact.ts", "utf8")),
};
type Row = { pattern: string; withinDoublingRatio: boolean; ratioEvaluated: boolean; withinAbsoluteCap: boolean | null; meetsBudget: boolean };
const oracle = fixture<{ behavior: { jwtScrub: { budget: typeof JWT_BUDGET; rows: Record<string, Row> } } }>("oracle.json").behavior.jwtScrub;

/** Retry up to `tries` times; true as soon as one attempt satisfies `want`. */
const eventually = (attempt: () => ReturnType<typeof measureScaling>, want: (r: ReturnType<typeof measureScaling>) => boolean, tries = 4) => {
  let last = attempt();
  for (let i = 1; i < tries && !want(last); i++) {
    last = attempt();
  }
  return { ok: want(last), last };
};

test("the oracle's patterns are the ones in the fixture and the repo, and its budget is the one the prompt states", () => {
  assert.deepEqual(oracle.budget, JWT_BUDGET);
  for (const [name, re] of Object.entries(PATTERNS)) {
    assert.equal(oracle.rows[name]!.pattern, String(re), name);
  }
});

test("jwt, measured: the pre-bound pattern fails the doubling ratio (quadratic)", () => {
  const { ok, last } = eventually(() => measureScaling(regexRunner(PATTERNS.at44ce7ea5, jwtInput)), (r) => !r.withinRatio);
  assert.ok(ok, JSON.stringify(last));
  assert.equal(oracle.rows.at44ce7ea5!.withinDoublingRatio, false);
});

test("jwt, measured: the bounded pattern passes the ratio (linear) and fails the absolute cap", () => {
  const { ok, last } = eventually(
    () => measureScaling(regexRunner(PATTERNS.atD578603e, jwtInput)),
    (r) => r.withinRatio && r.withinCap === false,
  );
  assert.ok(ok, JSON.stringify(last));
  assert.deepEqual([oracle.rows.atD578603e!.withinDoublingRatio, oracle.rows.atD578603e!.withinAbsoluteCap], [true, false]);
});

test("jwt, measured: the fixed head passes both", () => {
  const { ok, last } = eventually(() => measureScaling(regexRunner(PATTERNS.atHead88b72c5b, jwtInput)), (r) => r.meetsBudget);
  assert.ok(ok, JSON.stringify(last));
  assert.equal(oracle.rows.atHead88b72c5b!.meetsBudget, true);
});
