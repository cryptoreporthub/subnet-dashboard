import assert from "node:assert/strict";
import test from "node:test";
import { claimsToHaveRunCommands } from "../evals/claims.js";
import {
  PRONOUN_POSSESSIVE,
  REPRO_CASES,
  expectedRowCount,
  matrixRows,
} from "../evals/claim-matrix.js";

/**
 * The three reproduction strings measured at BASELINE-R29 before any matrix code
 * existed. They stay here as permanent cases with their measured values.
 *
 * S3 is the one r29 got wrong: a passive clause with its own subject ("their
 * python one-liner") and no I/we claimant must not be read as the bot's run
 * claim. r29 flagged it because the passive branch only checked that a target
 * was in reach, never who the clause was about.
 */
for (const { label, text, expected } of REPRO_CASES) {
  test(`${label} reproduction string classifies as ${expected}`, () => {
    assert.equal(claimsToHaveRunCommands(text), expected, text);
  });
}

const rows = matrixRows();

test("the matrix has exactly the number of cases its inputs generate", () => {
  // Derived from the arrays in evals/claim-matrix.ts; never a literal total.
  assert.equal(rows.length, expectedRowCount());
  assert.equal(
    rows.length + REPRO_CASES.length,
    expectedRowCount() + REPRO_CASES.length,
  );
});

test("every generated row classifies as its property says", () => {
  for (const row of rows) {
    assert.equal(
      claimsToHaveRunCommands(row.text),
      row.expected,
      `${row.kind} row: ${row.text}`,
    );
  }
});

test("no generated row splices a pronoun onto a possessive", () => {
  for (const row of rows) {
    assert.doesNotMatch(row.text, PRONOUN_POSSESSIVE, row.text);
  }
  // The invariant has teeth: the splice it forbids is rejected ...
  assert.match(
    "No commands were run, and I their python one-liner was executed.",
    PRONOUN_POSSESSIVE,
  );
  // ... while the legitimate active rows still pass it.
  for (const row of rows.filter((r) => r.kind === "active")) {
    assert.doesNotMatch(row.text, PRONOUN_POSSESSIVE, row.text);
  }
  assert.doesNotMatch("I ran their python one-liner.", PRONOUN_POSSESSIVE);
});

test("every passive row reads as English with its own subject", () => {
  for (const row of rows.filter((r) => r.kind === "passive")) {
    // "No commands were run, and <subject> <aux> <verb>."
    assert.match(
      row.text,
      /^No commands were run, and (?:their|his|her|its|the \w+'s) [^,]+? (?:was|were) (?:executed|run)\.$/,
      row.text,
    );
  }
});
