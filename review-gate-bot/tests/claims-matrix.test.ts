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

const rows = matrixRows();

test("the matrix has exactly the number of cases its inputs generate", () => {
  assert.equal(rows.length, expectedRowCount());
});

test("every generated row agrees with the detector", () => {
  for (const row of rows) {
    assert.equal(
      claimsToHaveRunCommands(row.text),
      row.expected,
      `${row.kind} row: ${row.text}`,
    );
  }
});

test("every axis is present", () => {
  assert.equal(new Set(rows.map((r) => r.lead)).size, 3);
  assert.deepEqual(new Set(rows.map((r) => r.lead)), new Set(LEADS));
  assert.equal(new Set(rows.map((r) => r.comma)).size, 2);
  assert.deepEqual(new Set(rows.map((r) => r.comma)), new Set(COMMA_STATES));
  assert.equal(new Set(rows.map((r) => r.connector)).size, 6);
  assert.deepEqual(new Set(rows.map((r) => r.connector)), new Set(CONNECTORS));
  assert.equal(new Set(rows.map((r) => r.text)).size, rows.length, "all rows are distinct");

  const activeSubjects = new Set(
    rows.filter((r) => r.kind === "active").map((r) => r.subject),
  );
  const causativeSubjects = new Set(
    rows.filter((r) => r.kind === "causative").map((r) => r.subject),
  );
  assert.deepEqual(activeSubjects, new Set(SUBJECTS));
  assert.deepEqual(causativeSubjects, new Set(SUBJECTS));

  const passive = rows.filter((r) => r.kind === "passive");
  assert.ok(passive.length > 0, "passive rows are present");
  for (const tail of PASSIVE_TAILS) {
    assert.ok(
      passive.some((r) => r.tail === tail),
      `passive tail is present: ${tail}`,
    );
  }

  assert.ok(ACTIVE_TAILS.length > 0 && CAUSATIVE_TAILS.length > 0);
});

test("no row splices a pronoun onto a possessive", () => {
  for (const row of rows) {
    assert.doesNotMatch(row.text, PRONOUN_SPLICE, row.text);
  }
  assert.match(
    "No commands were run, and I their python one-liner was executed.",
    PRONOUN_SPLICE,
  );
});

for (const { label, text, expected } of REPRO_CASES) {
  test(`${label} audit repro classifies as ${expected}`, () => {
    assert.equal(claimsToHaveRunCommands(text), expected, text);
  });
}
