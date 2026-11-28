import assert from "node:assert/strict";
import test from "node:test";
import { claimsToHaveRunCommands } from "../evals/claims.js";
import {
  ACTIVE_TAILS,
  CAUSATIVE_TAILS,
  COMMA_STATES,
  CONNECTORS,
  LEADS,
  PASSIVE_TAILS,
  PRONOUN_SPLICE,
  REPRO_CASES,
  SUBJECTS,
  expectedRowCount,
  matrixRows,
} from "../evals/claim-matrix.js";

/**
 * The three audit reproduction strings, kept as named cases. r31 pins all three
 * as run claims: the denial lead covers its own clause only, and a later claim is
 * the claim whatever its subject. S3 is the r30 false negative this round fixes.
 */
for (const { label, text, expected } of REPRO_CASES) {
  test(`${label} audit reproduction classifies as ${expected}`, () => {
    assert.equal(claimsToHaveRunCommands(text), expected, text);
  });
}

const rows = matrixRows();

test("the matrix has exactly the number of cases its inputs generate", () => {
  // Derived from the arrays in evals/claim-matrix.ts; never a literal total.
  assert.equal(rows.length, expectedRowCount());
  const base = LEADS.length * COMMA_STATES.length * CONNECTORS.length;
  assert.equal(
    rows.length,
    base *
      (SUBJECTS.length * ACTIVE_TAILS.length +
        SUBJECTS.length * CAUSATIVE_TAILS.length +
        PASSIVE_TAILS.length),
  );
});

test("every generated row classifies as its property says", () => {
  for (const row of rows) {
    assert.equal(
      claimsToHaveRunCommands(row.text),
      row.expected,
      `${row.voice} row: ${row.text}`,
    );
  }
});

test("every row expects true: a denial lead never licenses a later claim", () => {
  for (const row of rows) {
    assert.equal(row.expected, true, row.text);
  }
});

test("every axis of the cube is present", () => {
  assert.deepEqual([...new Set(rows.map((r) => r.lead))].sort(), [...LEADS].sort());
  assert.deepEqual(
    [...new Set(rows.map((r) => r.comma))].sort(),
    [...COMMA_STATES].sort(),
  );
  assert.deepEqual(
    [...new Set(rows.map((r) => r.connector))].sort(),
    [...CONNECTORS].sort(),
  );
  assert.equal(new Set(rows.map((r) => r.text)).size, rows.length, "rows are distinct");

  for (const voice of ["active", "causative"] as const) {
    const subjects = new Set(
      rows.filter((r) => r.voice === voice).map((r) => r.subject),
    );
    assert.deepEqual([...subjects].sort(), [...SUBJECTS].sort(), voice);
  }

  const passive = rows.filter((r) => r.voice === "passive");
  assert.ok(passive.length > 0, "passive rows exist");
  assert.ok(
    passive.every((r) => r.subject === null),
    "passive rows carry their own subject",
  );
});

test("no generated row splices a pronoun onto a possessive", () => {
  for (const row of rows) {
    assert.doesNotMatch(row.text, PRONOUN_SPLICE, row.text);
  }
  // The invariant has teeth: the splice it forbids is rejected ...
  assert.match(
    "No commands were run, and I their python one-liner was executed.",
    PRONOUN_SPLICE,
  );
  // ... while a legitimate possessive object still passes it.
  assert.doesNotMatch("I ran their python one-liner.", PRONOUN_SPLICE);
});
