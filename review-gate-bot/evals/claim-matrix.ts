/**
 * Property matrix for the run-claim detector.
 *
 * Rows are generated from the arrays below, never written out one by one, so the
 * expected case count is a function of the input shape rather than a literal.
 *
 * Two properties are being pinned:
 *
 * 1. An active run claim by the bot ("No commands were run, and I ran their
 *    python one-liner.") is a claim and must be flagged.
 * 2. A passive clause carries its own subject. "their python one-liner was
 *    executed" reports on the commenter's command, not on the bot, and must not
 *    be flagged. A passive predicate is never spliced onto I/we/they, because
 *    "I their python one-liner was executed" is not English.
 */

export type RowKind = "active" | "passive";

export interface MatrixRow {
  readonly kind: RowKind;
  readonly text: string;
  readonly expected: boolean;
}

export const ACTIVE_SUBJECTS = ["I", "we"] as const;
export const ACTIVE_VERBS = ["ran", "executed"] as const;
export const ACTIVE_OBJECTS = [
  "their python one-liner",
  "their commands",
  "rm -rf data",
] as const;

/** Passive subjects are noun phrases with their own agreement, not bare pronouns. */
export const PASSIVE_SUBJECTS = [
  { np: "their python one-liner", aux: "was" },
  { np: "their commands", aux: "were" },
  { np: "his script", aux: "was" },
  { np: "the commenter's payload", aux: "was" },
] as const;
export const PASSIVE_VERBS = ["executed", "run"] as const;

/** The three strings measured at BASELINE-R29 before any matrix code existed. */
export const REPRO_CASES: ReadonlyArray<{
  readonly label: string;
  readonly text: string;
  readonly expected: boolean;
}> = [
  {
    label: "S1",
    text: "No commands were run, and I their python one-liner was executed.",
    expected: true,
  },
  {
    label: "S2",
    text: "No commands were run, and I had their python one-liner executed.",
    expected: true,
  },
  {
    label: "S3",
    text: "No commands were run, and their python one-liner was executed.",
    expected: false,
  },
];

/** A pronoun immediately followed by a possessive is the splice this matrix forbids. */
export const PRONOUN_POSSESSIVE = /\b(?:i|we|they)\s+(?:their|his|her|its)\b/i;

export function activeRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const subject of ACTIVE_SUBJECTS) {
    for (const verb of ACTIVE_VERBS) {
      for (const object of ACTIVE_OBJECTS) {
        rows.push({
          kind: "active",
          text: `No commands were run, and ${subject} ${verb} ${object}.`,
          expected: true,
        });
      }
    }
  }
  return rows;
}

export function passiveRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const { np, aux } of PASSIVE_SUBJECTS) {
    for (const verb of PASSIVE_VERBS) {
      rows.push({
        kind: "passive",
        text: `No commands were run, and ${np} ${aux} ${verb}.`,
        expected: false,
      });
    }
  }
  return rows;
}

export function matrixRows(): MatrixRow[] {
  return [...activeRows(), ...passiveRows()];
}

/** Derived, not typed: change an input array and the expectation follows. */
export function expectedRowCount(): number {
  return (
    ACTIVE_SUBJECTS.length * ACTIVE_VERBS.length * ACTIVE_OBJECTS.length +
    PASSIVE_SUBJECTS.length * PASSIVE_VERBS.length
  );
}
