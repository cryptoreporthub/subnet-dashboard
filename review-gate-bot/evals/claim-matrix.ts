/**
 * Property matrix for the run-claim detector.
 *
 * Rows are generated from the arrays below, never written out one by one, so the
 * expected case count is a function of the input shape rather than a literal.
 *
 * Every row expects TRUE, and the reason is a rule, not a sample:
 *
 *   A denial lead does not license a later run claim, whatever the subject,
 *   the punctuation or the voice. "No commands were run, and they ran rm -rf
 *   data." denies the first clause and claims the second; the claim is the
 *   claim. This is the audit's rule and Joshua's recorded decision, and it
 *   supersedes the earlier suggestion that a third-party subject excuses the
 *   clause (r30 skipped "their python one-liner was executed" for that reason,
 *   which is the false negative this round removes).
 *
 * The cube is {lead} x {comma, no comma} x {connector} x {voice}:
 *   active    -> {subject} {active tail}, subject in I/we/they
 *   causative -> {subject} {causative tail}, subject in I/we/they
 *   passive   -> {passive tail}; a passive predicate supplies its own subject
 *                and is never spliced onto I/we/they ("I their one-liner was
 *                executed" is not English).
 */

export type RowVoice = "active" | "causative" | "passive";

export interface MatrixRow {
  readonly lead: string;
  readonly comma: boolean;
  readonly connector: string;
  readonly voice: RowVoice;
  /** Null for passive rows: the predicate carries its own subject. */
  readonly subject: string | null;
  readonly text: string;
  readonly expected: boolean;
}

export const LEADS = [
  "No commands were run",
  "None of the commands were run",
  "Nothing was run",
] as const;

/** Comma before the connector, or none: both read as the same denial-then-claim. */
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

export const PASSIVE_TAILS = [
  "their python one-liner was executed",
  "their commands were run",
  "their script was executed",
] as const;

/** The three audit reproduction strings, kept as named cases. All expect TRUE at r31. */
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
    // r30 expected false here. r31 supersedes that: the clause is a run claim
    // whatever its subject, so the matrix now pins true.
    label: "S3",
    text: "No commands were run, and their python one-liner was executed.",
    expected: true,
  },
];

/** A pronoun immediately followed by a possessive is the splice this matrix forbids. */
export const PRONOUN_SPLICE = /\b(?:i|we|they|he|she|it|you)\s+(?:their|his|her|its)\b/i;

function joinLead(lead: string, comma: boolean, connector: string): string {
  return comma ? `${lead}, ${connector} ` : `${lead} ${connector} `;
}

export function activeRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const lead of LEADS) {
    for (const comma of COMMA_STATES) {
      for (const connector of CONNECTORS) {
        for (const subject of SUBJECTS) {
          for (const tail of ACTIVE_TAILS) {
            rows.push({
              lead,
              comma,
              connector,
              voice: "active",
              subject,
              text: `${joinLead(lead, comma, connector)}${subject} ${tail}.`,
              expected: true,
            });
          }
        }
      }
    }
  }
  return rows;
}

export function causativeRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const lead of LEADS) {
    for (const comma of COMMA_STATES) {
      for (const connector of CONNECTORS) {
        for (const subject of SUBJECTS) {
          for (const tail of CAUSATIVE_TAILS) {
            rows.push({
              lead,
              comma,
              connector,
              voice: "causative",
              subject,
              text: `${joinLead(lead, comma, connector)}${subject} ${tail}.`,
              expected: true,
            });
          }
        }
      }
    }
  }
  return rows;
}

/** Passive predicates bring their own subject; they are never spliced onto a pronoun. */
export function passiveRows(): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const lead of LEADS) {
    for (const comma of COMMA_STATES) {
      for (const connector of CONNECTORS) {
        for (const tail of PASSIVE_TAILS) {
          rows.push({
            lead,
            comma,
            connector,
            voice: "passive",
            subject: null,
            text: `${joinLead(lead, comma, connector)}${tail}.`,
            expected: true,
          });
        }
      }
    }
  }
  return rows;
}

export function matrixRows(): MatrixRow[] {
  return [...activeRows(), ...causativeRows(), ...passiveRows()];
}

/** Derived, not typed: change an input array and the expectation follows. */
export function expectedRowCount(): number {
  const headed = LEADS.length * COMMA_STATES.length * CONNECTORS.length * SUBJECTS.length;
  return (headed * ACTIVE_TAILS.length +
    headed * CAUSATIVE_TAILS.length +
    LEADS.length * COMMA_STATES.length * CONNECTORS.length * PASSIVE_TAILS.length);
}
