/**
 * Refuse PASS when the review carries a performance or complexity figure that is
 * not tied to a same-line `measured` label from a tool return.
 */
const DURATION = /\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|sec(?:onds?)?)\b/i;
const COMPLEXITY = /\bO\s*\(\s*[^)]+\)/i;
const negatedMeasured = /\b(?:not|no|never|nor|cannot|can't|without|un)[\s-]{0,3}(?:\w+\s+){0,2}measured\b/gi;

export function passClaimsUnmeasuredPerf(text: string): boolean {
  return text.split("\n").some((line) => {
    if (!DURATION.test(line) && !COMPLEXITY.test(line)) {
      return false;
    }
    return !/\bmeasured\b/i.test(line.replace(negatedMeasured, ""));
  });
}
