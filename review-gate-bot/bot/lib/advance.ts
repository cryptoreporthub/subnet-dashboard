import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { postGateCheck, type CreateCheck } from "./check.js";
import { readGateState, type PrRef } from "./gh.js";
import { gateActions, prKey, reviewTurnKey } from "./gate.js";
import { lease } from "./lock.js";
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
  const reviewTurn = actions.needsReviewTurn && (await lease(kv, reviewTurnKey(ref, headSha), now));
  if (actions.needsReviewTurn && !reviewTurn) {
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
  const check = await attempt("check", () => postGateCheck({ octokit, kv, ref, state, createCheck }));

  return {
    headSha,
    draft,
    next: state.next,
    needsReviewTurn: reviewTurn,
    taggedCursorDitto,
    taggedReplit,
    replitAsk,
    check,
  };
}


/**
 * Free the review-turn lease for a head whose model turn failed or was cancelled, so the
 * next delivery for that head may ask again.
 *
 * Limits: a turn dropped by a host restart emits no event, so the lease then runs out on its
 * own TTL. The delete is unconditional, so it can free a lease a newer delivery has just
 * taken; the cost is one extra turn, not a second post. And once released, repeated failures
 * can start a new turn on every later event for that head.
 */
export async function releaseReviewTurn(kv: HostKvApi, ref: PrRef, headSha: string): Promise<void> {
  await kv.delete(reviewTurnKey(ref, headSha));
  console.warn(JSON.stringify({ level: "warn", event: "review_turn_lease_released", pr: prKey(ref), head: headSha }));
}

/**
 * `pull_request` delivery: does it start a model turn?
 *
 * The gate decides, from the live PR: a draft, or a head that already has an MC
 * verdict, needs none. The payload's own draft flag only short-circuits the
 * read.
 */
export async function pullRequestTurn(deps: GateDeps, pr: { action: string; draft: boolean }): Promise<boolean> {
  if (pr.draft || !REVIEW_ACTIONS.has(pr.action)) {
    return false;
  }
  // Tags first, in plain code, so they land even if the model turn fails.
  return (await advanceGate(deps)).needsReviewTurn;
}

/**
 * Comment delivery: does it start a model turn?
 *
 * The bot's own comments come back as webhooks and must not re-enter the gate.
 * They are authored by the App's bot login, which nobody else holds, so the
 * login alone is the test. The owner account is not: Joshua, MC, Claude, Ditto's
 * relayed comments and the Replit reports all post there.
 */
export async function commentTurn(deps: GateDeps, author: string | undefined): Promise<boolean> {
  if (author === GATE_BOT_LOGIN) {
    return false;
  }
  return (await advanceGate(deps)).needsReviewTurn;
}

/** `pull_request_review` delivery: does it start a model turn? */
export async function reviewEventTurn(deps: GateDeps): Promise<boolean> {
  return (await advanceGate(deps)).needsReviewTurn;
}
