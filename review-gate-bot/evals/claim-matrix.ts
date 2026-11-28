/**
 * Property matrix for the run-claim detector.
 *
 * Rows are generated from the arrays below, never written out one by one, so the
 * expected case count is a function of the input shape rather than a literal.
 *
 * The property being pinned: a denial lead does not license a later run claim,
 * whatever the subject, punctuation or voice. "No commands were run" denies the
 * run before it; a following active, causative or passive run claim is still a
 * claim and must be flagged. That is the audit's rule and Joshua's recorded
 * decision, superseding the earlier recommendation that a third-party subject
 * excuses the clause.
 *
 * Passive predicates supply their OWN subject and are never spliced onto
 * I/we/they, because "I their python one-liner was executed" is not English.
 */

export type RowKind = "active" | "causative" | "passive";

export interface MatrixRow {
  readonly kind: RowKind;
  readonly lead: string;
  readonly comma: boolean;
  readonly connector: string;
  readonly subject?: string;
  readonly tail: string;
  readonly text: string;
  readonly expected: boolean;
}

export const LEADS = [
  "No commands were run",
  "None of the commands were run",
  "Nothing was run",
] as const;

/** true inserts a comma before the connector; false is the bare-space form. */
export const COMMA_STATES = [true, false] as const;

export const CONNECTORS = ["and", "but", "so", "then", "yet", "while"] as const;

export const SUBJECTS = ["I", "we", "they"] as const;

export const ACTIVE_TAILS = [
  "ran rm -rf data",
  "executed their python one-liner",
] as const;

export const CAUSATIVE_TAILS = [
  "got their commands run",
  "had their python one-liner executed",
] as const;

/** Passive subjects are noun phrases with their own agreement, not bare pronouns. */
export const PASSIVE_TAILS = [
  "their python one-liner was executed",
  "their commands were run",
  "their script was executed",
] as const;

/** A pronoun immediately followed by a possessive is the splice this matrix forbids. */
export const PRONOUN_SPLICE = /\b(?:i|we|they)\s+(?:their|his|her|its)\b/i;

/** The three no-comma audit repros. All must be flagged after r31. */
export const REPRO_CASES: ReadonlyArray<{
  readonly label: string;
  readonly text: string;
  readonly expected: boolean;
}> = [
  {
    label: "S1",
    text: "No commands were run and they ran rm -rf data.",
    expected: true,
  },
  {
    label: "S2",
    text: "No commands were run and their python one-liner was executed.",
    expected: true,
  },
  {
    label: "S3",
    text: "No commands were run and got their commands run.",
    expected: true,
  },
];

function makeText(lead: string, comma: boolean, connector: string, tail: string): string {
  return `${lead}${comma ? "," : ""} ${connector} ${tail}.`;
}

function subjectRows(kind: "active" | "causative", tails: readonly string[]): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const lead of LEADS) {
    for (const comma of COMMA_STATES) {
      for (const connector of CONNECTORS) {
        for (const subject of SUBJECTS) {
          for (const tail of tails) {
            rows.push({
              kind,
              lead,
              comma,
              connector,
              subject,
              tail,
              text: makeText(lead, comma, connector, `${subject} ${tail}`),
              expected: true,
            });
          }
        }
      }
    }
  }
  return rows;
}

export function passiveRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const lead of LEADS) {
    for (const comma of COMMA_STATES) {
      for (const connector of CONNECTORS) {
        for (const tail of PASSIVE_TAILS) {
          rows.push({
            kind: "passive",
            lead,
            comma,
            connector,
            tail,
            text: makeText(lead, comma, connector, tail),
            expected: true,
          });
        }
      }
    }
  }
  return rows;
}

export function activeRows(): MatrixRow[] {
  return subjectRows("active", ACTIVE_TAILS);
}

export function causativeRows(): MatrixRow[] {
  return subjectRows("causative", CAUSATIVE_TAILS);
}

export function matrixRows(): MatrixRow[] {
  return [...activeRows(), ...causativeRows(), ...passiveRows()];
}

/** Derived, not typed: change an input array and the expectation follows. */
export function expectedRowCount(): number {
  return (
    LEADS.length *
      COMMA_STATES.length *
      CONNECTORS.length *
      SUBJECTS.length *
      (ACTIVE_TAILS.length + CAUSATIVE_TAILS.length) +
    LEADS.length * COMMA_STATES.length * CONNECTORS.length * PASSIVE_TAILS.length
  );
}
