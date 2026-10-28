import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { postGateCheck, type CreateCheck } from "./check.js";
import { readGateState, type PrRef } from "./gh.js";
import { gateActions, prKey, reviewTurnKey } from "./gate.js";
import { leaseToken, releaseLeaseIfHolder } from "./lock.js";
import { askReplitOnce, type ReplitAskOutcome } from "./replit.js";
import { tagCursorAndDitto, tagReplit } from "./tag.js";
import { GATE_BOT_LOGIN } from "./verdicts.js";

/** What the gate needs from the host: plain handles, so it can run without the SDK. */
export type GateDeps = {
  octokit: Octokit;
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  /** `ctx.github.createCheck`: opens the `review-gate` check run on a commit. */
  createCheck: CreateCheck;
  /** The clock the review-turn lease reads. Defaults to `Date.now`. */
  now?: () => number;
};

/**
 * PR actions that start a review turn.
 *
 * `synchronize` is included on purpose: a new head resets every verdict, so it
 * must re-review. A duplicate delivery is harmless because the per-head lock
 * refuses a second review of the same SHA.
 */
export const REVIEW_ACTIONS = new Set(["opened", "synchronize", "reopened", "ready_for_review"]);

/**
 * The head and draft flag, read live.
 *
 * Every hook re-reads this rather than trusting the delivery payload: a hook
 * can fire on a draft, and a draft must never be tagged or reviewed — the
 * reviewer round trip is for a PR that is actually asking for review.
 */
async function readHead(octokit: Octokit, ref: PrRef): Promise<{ headSha: string; draft: boolean }> {
  const { data } = await octokit.rest.pulls.get({
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
  });
  return { headSha: data.head.sha, draft: data.draft ?? false };
}

export type AdvanceResult = {
  headSha: string;
  draft: boolean;
  next: string;
  needsReviewTurn: boolean;
  /** The lease a granted review turn holds, to carry on the turn and release on failure. */
  reviewLease?: ReviewTurnLease;
  taggedCursorDitto: string;
  taggedReplit: string;
  replitAsk: string;
  check: string;
};

/**
 * One structured line for an ask that will not succeed. A silent failure here
 * used to mean Replit was never asked and nobody knew.
 */
export function logAsk(outcome: ReplitAskOutcome, pr: string, headSha: string): void {
  if (outcome.asked || outcome.reason === "already-asked" || !outcome.persistent) {
    return;
  }
  console.error(
    JSON.stringify({
      level: "error",
      event: "replit_ask_persistent_failure",
      pr,
      head: headSha,
      reason: outcome.reason,
      attempts: outcome.attempts,
      detail: outcome.detail,
      effect:
        "Replit was never successfully asked for this head. The gate does not advance on the ask: it still needs Replit's posted verdict, which will arrive only if the @replit tag reaches them.",
    }),
  );
}

function askLabel(outcome: ReplitAskOutcome): string {
  if (outcome.asked) {
    return "asked";
  }
  if (outcome.reason === "already-asked") {
    return "already-asked";
  }
  return outcome.persistent ? `failed:persistent:${outcome.reason}` : `failed:${outcome.reason}`;
}

/**
 * Re-read the gate for the PR's current head and post whatever tags it allows.
 *
 * No model turn and no judgement: `lib/gate.ts` decides (`gateActions`), this
 * only delivers. Every post is lock-guarded per head, so a replay or a
 * duplicate webhook runs this again without repeating a comment.
 *
 * **Draft guard.** A draft is returned before anything is posted or asked. The
 * pull_request hook had this check; the comment and event hooks did not, so a
 * comment on a draft PR tagged both reviewers. The decision lives in
 * `gateActions`, so all three hooks refuse a draft the same way.
 */
export async function advanceGate(deps: GateDeps): Promise<AdvanceResult> {
  const { octokit, kv, mcp, ref, createCheck, now } = deps;
  const { headSha, draft } = await readHead(octokit, ref);

  if (draft) {
    return {
      headSha,
      draft,
      next: "review",
      needsReviewTurn: false,
      taggedCursorDitto: "skipped:draft",
      taggedReplit: "skipped:draft",
      replitAsk: "skipped:draft",
      check: "skipped:draft",
    };
  }

  const state = await readGateState({ octokit, kv, ref, headSha });
  const actions = gateActions(state, false);

  // Every delivery for this head reads the same missing verdict, so each would
  // ask for a review turn. Only the one that takes the lease asks.
  const token = actions.needsReviewTurn ? await leaseToken(kv, reviewTurnKey(ref, headSha), now) : undefined;
  const reviewLease: ReviewTurnLease | undefined = token === undefined ? undefined : { head: headSha, token };
  if (actions.needsReviewTurn && reviewLease === undefined) {
    console.warn(JSON.stringify({ level: "warn", event: "review_turn_lease_held", pr: prKey(ref), head: headSha }));
  }

  // A failing post must not lose the review turn that follows it, and must not
  // stop the next step: each is logged and reported, then the gate moves on.
  const attempt = async (step: string, body: () => Promise<string>): Promise<string> => {
    try {
      return await body();
    } catch (error) {
      console.error(
        JSON.stringify({
          level: "error",
          event: "gate_step_failed",
          step,
          pr: prKey(ref),
          head: headSha,
          error: error instanceof Error ? error.message : String(error),
        }),
      );
      return `failed:${step}`;
    }
  };

  // The Cursor/Ditto tag is posted on every head, so the round trip starts
  // immediately and does not wait for MC's verdict to be written down.
  const taggedCursorDitto = actions.tagCursorDitto
    ? await attempt("tag-cursor-ditto", async () => (await tagCursorAndDitto({ octokit, kv, ref, headSha, state })).reason)
    : "skipped";

  const taggedReplit = actions.tagReplit
    ? await attempt("tag-replit", async () => (await tagReplit({ octokit, kv, ref, headSha, currentHeadSha: headSha })).reason)
    : "skipped";

  // The ask follows the tag. When this delivery had to post the tag, the ask
  // waits for confirmation that it is on the PR (posted now, or already there);
  // a failed or contested tag post must not be followed by an ask. In
  // `await_replit` the tag is known to exist, so a failed ask is retried freely.
  const tagConfirmed = taggedReplit === "posted" || taggedReplit === "already-posted";
  const replitAsk =
    actions.askReplit && (!actions.tagReplit || tagConfirmed)
      ? await attempt("ask-replit", async () => {
          const ask = await askReplitOnce({ kv, mcp, ref, headSha });
          logAsk(ask, prKey(ref), headSha);
          return askLabel(ask);
        })
      : "skipped";

  // The check reports the gate as read at the top of this delivery; a verdict
  // posted later arrives as its own event and replaces it.
  const check = await attempt("check", () =>
    postGateCheck({ octokit, kv, ref, state, createCheck, read: () => readGateState({ octokit, kv, ref, headSha }) }),
  );

  return {
    headSha,
    draft,
    next: state.next,
    needsReviewTurn: reviewLease !== undefined,
    reviewLease,
    taggedCursorDitto,
    taggedReplit,
    replitAsk,
    check,
  };
}

/** A review turn's lease: the head it is for and the token that proves it is this turn's. */
export type ReviewTurnLease = { head: string; token: string };

/**
 * Whether a failed turn gives its lease back. A `cancelled` turn was stopped, or preempted by a
 * follow-up, and a replacement may already be running for the same head: releasing then starts
 * a second turn beside it. Only an error frees the lease.
 */
export function failureReleasesLease(status: string | undefined): boolean {
  return status !== "cancelled";
}

/**
 * Give back a granted review turn's lease, but only if it is still this turn's. The lease is
 * freed when its own token is stored under its key; a later turn's lease, or a lease that
 * expired and was retaken, has another token and is left alone. A lost lease falls back to
 * the TTL.
 */
export async function releaseReviewTurnIfHolder(kv: HostKvApi, ref: PrRef, lease: ReviewTurnLease): Promise<boolean> {
  const released = await releaseLeaseIfHolder(kv, reviewTurnKey(ref, lease.head), lease.token);
  console.warn(
    JSON.stringify({
      level: "warn",
      event: released ? "review_turn_lease_released" : "review_turn_lease_not_held",
      pr: prKey(ref),
      head: lease.head,
    }),
  );
  return released;
}

/**
 * The lease a turn was started with, read from its channel state. Anything not exactly the
 * shape the bot wrote is no lease, so a missing or garbled state releases nothing.
 */
export function reviewLeaseFromState(value: unknown): ReviewTurnLease | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const lease = (value as { reviewLease?: unknown }).reviewLease;
  if (typeof lease !== "object" || lease === null) {
    return undefined;
  }
  const { head, token } = lease as { head?: unknown; token?: unknown };
  if (typeof head !== "string" || !/^[0-9a-f]{40}$/.test(head)) {
    return undefined;
  }
  if (typeof token !== "string" || !/^[A-Za-z0-9-]{1,80}$/.test(token)) {
    return undefined;
  }
  return { head, token };
}

/**
 * `pull_request` delivery: does it start a model turn?
 *
 * The gate decides, from the live PR: a draft, or a head that already has an MC
 * verdict, needs none. The payload's own draft flag only short-circuits the
 * read.
 */
export async function pullRequestReviewTurn(
  deps: GateDeps,
  pr: { action: string; draft: boolean },
): Promise<ReviewTurnLease | undefined> {
  if (pr.draft || !REVIEW_ACTIONS.has(pr.action)) {
    return undefined;
  }
  // Tags first, in plain code, so they land even if the model turn fails.
  return (await advanceGate(deps)).reviewLease;
}

export async function pullRequestTurn(deps: GateDeps, pr: { action: string; draft: boolean }): Promise<boolean> {
  return (await pullRequestReviewTurn(deps, pr)) !== undefined;
}

/**
 * Comment delivery: does it start a model turn?
 *
 * The bot's own comments come back as webhooks and must not re-enter the gate.
 * They are authored by the App's bot login, which nobody else holds, so the
 * login alone is the test. The owner account is not: Joshua, MC, Claude, Ditto's
 * relayed comments and the Replit reports all post there.
 */
export async function commentReviewTurn(deps: GateDeps, author: string | undefined): Promise<ReviewTurnLease | undefined> {
  if (author === GATE_BOT_LOGIN) {
    return undefined;
  }
  return (await advanceGate(deps)).reviewLease;
}

export async function commentTurn(deps: GateDeps, author: string | undefined): Promise<boolean> {
  return (await commentReviewTurn(deps, author)) !== undefined;
}

/** `pull_request_review` delivery: does it start a model turn? */
export async function reviewEventReviewTurn(deps: GateDeps): Promise<ReviewTurnLease | undefined> {
  return (await advanceGate(deps)).reviewLease;
}

export async function reviewEventTurn(deps: GateDeps): Promise<boolean> {
  return (await reviewEventReviewTurn(deps)) !== undefined;
}
