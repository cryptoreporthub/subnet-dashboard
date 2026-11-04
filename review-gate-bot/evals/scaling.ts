/**
 * How the hard exam measures "scrubs in bounded time" (case 9, `miss-jwt-scrub-slow`). Pure and clock-injected:
 * `measureScaling` takes a function that returns the milliseconds one run took, so `tests/hard-scaling.test.ts`
 * can prove the tolerance logic with scripted numbers and no machine in the loop.
 *
 * ## Why not "20 regex steps per character"
 *
 * JavaScript does not expose a regex step count, so a step budget is an estimate nobody can reproduce. What can be
 * reproduced is timing, in three parts, each chosen so CI noise cannot flip it:
 *
 * 1. **Doubling ratio.** Time the same input shape at N and at 2N characters and bound t(2N) / t(N). Linear work gives
 *    about 2, quadratic about 4. The bound is 3.0, a 50% tolerance over linear, half way to quadratic.
 * 2. **Noise floor.** Below `noiseFloorMs` at N the ratio is not evaluated, because a timer reading of a fraction of a
 *    millisecond is mostly noise. A run that fast cannot be growing quadratically at this size; the cap below still applies.
 * 3. **Absolute cap.** At `capChars` the scrub must finish within `capMs`. This is what catches a pattern that is
 *    linear but with a huge constant (a bounded `{8,2048}` that still rescans 2,048 characters from every `eyJ`),
 *    which the ratio cannot see. The cap is set 6x under what that pattern measured on the reference machine and 50x
 *    over the fixed head, so a machine several times faster or slower than the reference keeps the same verdicts.
 *
 * Every timing is the minimum of `repeats` runs after one warm-up run: noise only ever adds time, so the minimum is
 * the least noisy estimate of the work itself.
 */

export type ScalingBudget = {
  /** N: the smaller size, in characters. 2N is the larger. */
  chars: number;
  ratioMax: number;
  noiseFloorMs: number;
  capChars: number;
  capMs: number;
  repeats: number;
};

export const JWT_BUDGET: ScalingBudget = { chars: 10_000, ratioMax: 3.0, noiseFloorMs: 5, capChars: 200_000, capMs: 50, repeats: 3 };

/** The pinned input of the case: `eyJ-` repeated, no dots, so no JWT ever completes. */
export const jwtInput = (chars: number): string => "eyJ-".repeat(Math.ceil(chars / 4)).slice(0, chars);

export type ScalingResult = {
  msN: number;
  ms2N: number;
  ratio: number;
  /** False when t(N) was under the noise floor and the ratio was not evaluated. */
  ratioEvaluated: boolean;
  withinRatio: boolean;
  /** null when the cap run was skipped because the ratio had already failed (a quadratic pattern at 200,000 characters takes minutes). */
  msCap: number | null;
  withinCap: boolean | null;
  meetsBudget: boolean;
};

/** One timed run: the milliseconds the scrub of `chars` characters took. */
export type Runner = (chars: number) => number;

const best = (runner: Runner, chars: number, repeats: number): number => {
  runner(chars); // warm-up: the first run pays for compilation
  return Math.min(...Array.from({ length: repeats }, () => runner(chars)));
};

export function measureScaling(runner: Runner, budget: ScalingBudget = JWT_BUDGET): ScalingResult {
  const msN = best(runner, budget.chars, budget.repeats);
  const ms2N = best(runner, budget.chars * 2, budget.repeats);
  const ratioEvaluated = msN >= budget.noiseFloorMs;
  const ratio = msN > 0 ? ms2N / msN : 0;
  const withinRatio = !ratioEvaluated || ratio <= budget.ratioMax;
  if (!withinRatio) {
    return { msN, ms2N, ratio, ratioEvaluated, withinRatio, msCap: null, withinCap: null, meetsBudget: false };
  }
  const msCap = best(runner, budget.capChars, budget.repeats);
  const withinCap = msCap <= budget.capMs;
  return { msN, ms2N, ratio, ratioEvaluated, withinRatio, msCap, withinCap, meetsBudget: withinCap };
}

/** A real timer over one pattern: `String.prototype.replace` with the global pattern, as `redact.ts` does. */
export function regexRunner(pattern: RegExp, input: (chars: number) => string = jwtInput): Runner {
  return (chars) => {
    const text = input(chars);
    pattern.lastIndex = 0;
    const start = process.hrtime.bigint();
    text.replace(pattern, "[redacted]");
    return Number(process.hrtime.bigint() - start) / 1e6;
  };
}

/** The JWT pattern in a `redact.ts` source: the `/.../g` literal on the line that holds `eyJ`. */
export function extractJwtPattern(source: string): RegExp {
  const line = source.split("\n").find((l) => /^\s*\/.*eyJ.*\/[a-z]*,?\s*$/.test(l));
  if (line === undefined) {
    throw new Error("no JWT pattern literal in this redact.ts");
  }
  const m = /^\s*\/(.*)\/([a-z]*),?\s*$/.exec(line)!;
  return new RegExp(m[1]!, m[2]!);
}
