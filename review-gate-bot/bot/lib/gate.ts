/**
 * Pure gate order. No SDK import, no I/O, no model: the same inputs always
 * give the same `next`. Everything else (GitHub reads, kv, posting) lives in
 * `lib/` or `bot/tools/` and feeds this module.
 */

export type Verdict = "PASS" | "MODIFY" | "FAIL";
export type Reviewer = "mc" | "cursor" | "ditto" | "replit";

/** A formal verdict as read back from GitHub, already pinned to a head SHA. */
export type PinnedVerdict = {
  reviewer: Reviewer;
  headSha: string;
  verdict: Verdict;
};

export type SuiteState = "clean" | "regressed" | "carried" | "missing";

export type GateNext =
  | "review"
  | "await_cursor_ditto"
  | "run_suite"
  | "tag_replit"
  | "await_replit"
  | "mergeable"
  | "blocked";

export type GateInput = {
  headSha: string;
  /** Every formal verdict known for this PR, at any head. */
  verdicts: readonly PinnedVerdict[];
  suite: SuiteState;
  /** Head SHA the @replit tag was posted for, when it was. */
  replitTaggedForSha?: string;
};

export type GateState = {
  headSha: string;
  /** `missing` means no formal verdict for this reviewer at this exact head. */
  mc: Verdict | "missing";
  cursor: Verdict | "missing";
  ditto: Verdict | "missing";
  replit: Verdict | "missing";
  suite: SuiteState;
  replitTagged: boolean;
  next: GateNext;
};

/**
 * The verdict for one reviewer at one head. A head change resets every verdict,
 * so a verdict recorded at another SHA never counts here. When a reviewer has
 * several verdicts at one head, the latest one wins and the caller passes them
 * in that order.
 */
export function verdictAt(
  verdicts: readonly PinnedVerdict[],
  reviewer: Reviewer,
  headSha: string,
): Verdict | "missing" {
  let found: Verdict | "missing" = "missing";
  for (const v of verdicts) {
    if (v.reviewer === reviewer && v.headSha === headSha) {
      found = v.verdict;
    }
  }
  return found;
}

/** Any FAIL anywhere short-circuits the gate to `blocked`. */
function anyFail(state: { mc: unknown; cursor: unknown; ditto: unknown; replit: unknown }): boolean {
  return (
    state.mc === "FAIL" || state.cursor === "FAIL" || state.ditto === "FAIL" || state.replit === "FAIL"
  );
}

/**
 * The gate order:
 * MC pass at head -> Cursor pass at head -> Ditto pass at head ->
 * clean full-suite comparison -> @replit tagged -> Replit pass -> mergeable.
 */
export function computeGate(input: GateInput): GateState {
  const mc = verdictAt(input.verdicts, "mc", input.headSha);
  const cursor = verdictAt(input.verdicts, "cursor", input.headSha);
  const ditto = verdictAt(input.verdicts, "ditto", input.headSha);
  const replit = verdictAt(input.verdicts, "replit", input.headSha);
  const replitTagged = input.replitTaggedForSha === input.headSha;

  const base: GateState = {
    headSha: input.headSha,
    mc,
    cursor,
    ditto,
    replit,
    suite: input.suite,
    replitTagged,
    next: "review",
  };

  if (anyFail({ mc, cursor, ditto, replit })) {
    return { ...base, next: "blocked" };
  }

  if (mc !== "PASS") {
    // No MC verdict at this head yet: the gate's own review is the next step.
    return { ...base, next: "review" };
  }

  if (cursor !== "PASS" || ditto !== "PASS") {
    return { ...base, next: "await_cursor_ditto" };
  }

  if (input.suite !== "clean" && input.suite !== "carried") {
    return { ...base, next: "run_suite" };
  }

  if (!replitTagged) {
    return { ...base, next: "tag_replit" };
  }

  if (replit !== "PASS") {
    return { ...base, next: "await_replit" };
  }

  return { ...base, next: "mergeable" };
}

/** The single comment body that tags both reviewers, posted once per head. */
export function cursorDittoTagBody(headSha: string): string {
  return `@cursor review\n@ditto review\n\nHead under review: \`${headSha}\`. Requested automatically by the review gate.`;
}

/** The single comment body that tags Replit, posted once per head. */
export function replitTagBody(headSha: string): string {
  return `@replit review\n\nHead under review: \`${headSha}\`. MC and Cursor and Ditto all passed this head and the full-suite comparison is clean. Requested automatically by the review gate.`;
}

/** Key for the cursor/ditto tag lock. One tag per (PR, head). */
export function cursorDittoTagKey(prNumber: number, headSha: string): string {
  return `tag:${prNumber}:${headSha}:cursor-ditto`;
}

/** Key for the @replit tag lock. Deliberately separate from the cursor/ditto key. */
export function replitTagKey(prNumber: number, headSha: string): string {
  return `tag:${prNumber}:${headSha}:replit`;
}

/** Key for the Replit MCP ask. Sent once per head, after the @replit tag. */
export function replitAskKey(prNumber: number, headSha: string): string {
  return `ask:${prNumber}:${headSha}:replit`;
}
