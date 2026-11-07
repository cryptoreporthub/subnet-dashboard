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
  /** When the verdict was last said (ISO time). Needed to order a verdict against the Replit tag. */
  at?: string;
};

/** `needs-joshua` is final: a person has to clear it, so the gate stops asking for a suite run again. */
export type SuiteState = "clean" | "regressed" | "carried" | "missing" | "needs-joshua";

export type GateNext =
  | "review"
  | "await_cursor_ditto"
  | "run_suite"
  | "tag_replit"
  | "await_replit"
  | "needs_joshua"
  | "compare_blocked"
  | "mergeable"
  | "blocked";

export type GateInput = {
  headSha: string;
  /** Every formal verdict known for this PR, at any head. */
  verdicts: readonly PinnedVerdict[];
  suite: SuiteState;
  /** Why the suite needs Joshua: the files or test IDs behind it. Shown in the check. */
  suiteDetail?: string;
  /** Head SHA the @replit tag was posted for, when it was. */
  replitTaggedForSha?: string;
  /** When that tag was posted (ISO time). A Replit PASS counts only if said at or after it. */
  replitTaggedAt?: string;
  /**
   * When true, the automated PR file compare path is blocked (R-D1 / compare_blocked).
   * Distinct from `run_suite`: the gate does not ask the delivery to record a suite run.
   */
  compareBlocked?: boolean;
};

export type GateState = {
  headSha: string;
  /** `missing` means no formal verdict for this reviewer at this exact head. */
  mc: Verdict | "missing";
  cursor: Verdict | "missing";
  ditto: Verdict | "missing";
  replit: Verdict | "missing";
  suite: SuiteState;
  /** Why the suite needs Joshua, when it does. */
  suiteDetail?: string;
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
  const mine = verdicts.filter((v) => v.reviewer === reviewer && v.headSha === headSha);
  const last = mine.at(-1);
  if (last === undefined) {
    return "missing";
  }
  // Verdicts said at the same instant have no known order, so if they disagree none of them is the latest.
  // The instant is compared as a time, not as text: `...:00Z` and `...:00.000+00:00` are one moment.
  // A verdict whose time cannot be read has no known place in the order either, so it joins the group.
  // A FAIL still blocks; anything else asks for a fresh review rather than passing on an order nobody can see.
  const timeOf = (v: PinnedVerdict): number | undefined => (v.at === undefined ? undefined : Date.parse(v.at));
  const lastTime = timeOf(last);
  // A verdict with no readable time may sit anywhere in the order, so it is never assumed to be the latest on its own.
  // When the latest verdict has no readable time, nothing can be ordered: every verdict at this head is in the group.
  const readable = (v: PinnedVerdict): boolean => {
    const t = timeOf(v);
    return t !== undefined && !Number.isNaN(t);
  };
  // No readable time: every verdict joins the simultaneous group below (fail closed on disagreement).
  // A disagreement stays stuck until a new head is pushed; that is the exit.
  const simultaneous = (
    lastTime === undefined || Number.isNaN(lastTime)
      ? mine
      : mine.filter((v) => {
          const t = timeOf(v);
          return t === undefined || Number.isNaN(t) || t === lastTime;
        })
  ).map((v) => v.verdict);
  if (new Set(simultaneous).size > 1) {
    return simultaneous.includes("FAIL") ? "FAIL" : "MODIFY";
  }
  return last.verdict;
}

/** Any FAIL anywhere short-circuits the gate to `blocked`. */
function anyFail(state: { mc: unknown; cursor: unknown; ditto: unknown; replit: unknown }): boolean {
  return (
    state.mc === "FAIL" || state.cursor === "FAIL" || state.ditto === "FAIL" || state.replit === "FAIL"
  );
}

/**
 * Whether a verdict may count toward the gate. Only a Replit PASS is tied to the tag: it answers
 * the tag, so one said before this head's tag, or with no known time, answers nothing. Replit's
 * MODIFY and FAIL count whenever they were said, since a block must never be filtered out by time.
 */
function replitCounts(v: PinnedVerdict, tagAt: string | undefined): boolean {
  if (v.reviewer !== "replit" || v.verdict !== "PASS") {
    return true;
  }
  if (tagAt === undefined || v.at === undefined) {
    return false;
  }
  return Date.parse(v.at) >= Date.parse(tagAt);
}

/**
 * The gate order:
 * MC pass at head -> Cursor pass at head -> Ditto pass at head ->
 * clean full-suite comparison -> @replit tagged -> Replit pass -> mergeable.
 */
export function computeGate(input: GateInput): GateState {
  const replitTagged = input.replitTaggedForSha === input.headSha;
  const verdicts = input.verdicts.filter((v) => replitCounts(v, replitTagged ? input.replitTaggedAt : undefined));
  const mc = verdictAt(verdicts, "mc", input.headSha);
  const cursor = verdictAt(verdicts, "cursor", input.headSha);
  const ditto = verdictAt(verdicts, "ditto", input.headSha);
  const replit = verdictAt(verdicts, "replit", input.headSha);

  const base: GateState = {
    headSha: input.headSha,
    mc,
    cursor,
    ditto,
    replit,
    suite: input.suite,
    suiteDetail: input.suiteDetail,
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

  if (input.compareBlocked === true) {
    return { ...base, next: "compare_blocked", suiteDetail: input.suiteDetail };
  }

  if (input.suite === "needs-joshua") {
    // Final: a refused suite is not run again, and the check says why, until a person clears it or the head moves.
    return { ...base, next: "needs_joshua" };
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

/**
 * Should this gate state start a model turn?
 *
 * A turn exists to produce MC's own verdict, so it is spent only when there is
 * no MC verdict at this head. `next: "review"` alone is not the test:
 * `computeGate` returns `review` both for a missing MC verdict and for an MC
 * MODIFY, and re-reviewing a head that already has a verdict would post nothing
 * (`post_verdict` is at-most-once) while burning a turn on every later comment.
 */
export function needsReviewTurn(state: GateState): boolean {
  return state.next === "review" && state.mc === "missing";
}

/** What the channel should do for one delivery. Decided here, delivered there. */
export type GateActions = {
  /** A draft is never tagged, asked about, or reviewed. */
  draft: boolean;
  tagCursorDitto: boolean;
  tagReplit: boolean;
  askReplit: boolean;
  /** The gate needs the full-suite comparison recorded before it can go on. */
  runSuite: boolean;
  needsReviewTurn: boolean;
};

/**
 * The whole delivery decision, pure.
 *
 * The draft guard lives here rather than in each hook because it was only in
 * `onPullRequest`: `onComment` and `onEvent` tagged drafts. One function all
 * three hooks call means a draft cannot be handled three different ways.
 *
 * The Replit ask is allowed from `tag_replit` *and* `await_replit`. Asking only
 * in the first state meant a failed ask was never retried once the tag was
 * recorded. The ask never advances the gate: only Replit's posted verdict does.
 */
export function gateActions(state: GateState, draft: boolean): GateActions {
  if (draft) {
    return {
      draft: true,
      tagCursorDitto: false,
      tagReplit: false,
      askReplit: false,
      runSuite: false,
      needsReviewTurn: false,
    };
  }
  return {
    draft: false,
    tagCursorDitto: state.next !== "blocked",
    tagReplit: state.next === "tag_replit",
    askReplit: state.next === "tag_replit" || state.next === "await_replit",
    runSuite: state.next === "run_suite",
    needsReviewTurn: needsReviewTurn(state),
  };
}

/** The single comment body that tags both reviewers, posted once per head. */
export function cursorDittoTagBody(headSha: string): string {
  return `@cursor review\n@ditto review\n\nHead under review: \`${headSha}\`. Requested automatically by the review gate.`;
}

/** The single comment body that tags Replit, posted once per head. */
export function replitTagBody(headSha: string): string {
  return `@replit review\n\nHead under review: \`${headSha}\`. MC and Cursor and Ditto all passed this head and the full-suite comparison is clean. Requested automatically by the review gate.`;
}

/**
 * A PR's identity across repositories. The number alone is not unique: one kv
 * store could hold PR 1522 from two repositories.
 */
export function prKey(ref: { owner: string; repo: string; number: number }): string {
  return `${ref.owner}/${ref.repo}#${ref.number}`;
}

/** Key for the cursor/ditto tag lock. One tag per (PR, head). */
export function cursorDittoTagKey(ref: { owner: string; repo: string; number: number }, headSha: string): string {
  return `tag:${prKey(ref)}:${headSha}:cursor-ditto`;
}

/** Key for the @replit tag lock. Deliberately separate from the cursor/ditto key. */
export function replitTagKey(ref: { owner: string; repo: string; number: number }, headSha: string): string {
  return `tag:${prKey(ref)}:${headSha}:replit`;
}

/** Key for the Replit MCP ask. Sent once per head, after the @replit tag. */
export function replitAskKey(ref: { owner: string; repo: string; number: number }, headSha: string): string {
  return `ask:${prKey(ref)}:${headSha}:replit`;
}

/**
 * Key for the review-turn lease. One turn per (PR, head): a burst of deliveries
 * reads the same missing verdict, and only the one that takes the lease runs it.
 */
export function reviewTurnKey(ref: { owner: string; repo: string; number: number }, headSha: string): string {
  return `review-turn:${prKey(ref)}:${headSha}`;
}

/**
 * Fingerprint of human / compare holds that must stay tied to the deduped check (plan §4.1 FP-write).
 * Omits normal gate progression (`next`, suite clean/carried) so suite records written at `run_suite`
 * still match the fingerprint when the gate later reaches `mergeable`.
 */
export function checkHoldFingerprint(state: GateState): string {
  const parts: string[] = ["v1"];
  if (state.next === "compare_blocked") {
    parts.push("compare_blocked");
    const sd = state.suiteDetail ?? "";
    if (sd !== "") {
      parts.push(`sd=${sd}`);
    }
  }
  if (state.suite === "needs-joshua") {
    parts.push("needs_joshua");
    const sd = state.suiteDetail ?? "";
    if (sd !== "") {
      parts.push(`sd=${sd}`);
    }
  }
  return parts.join("|");
}
