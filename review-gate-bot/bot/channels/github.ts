import {
  defaultGitHubAuth,
  githubChannel,
  type GitHubEventContext,
} from "@grok/agent-sdk/channels/github";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { readGateState, type PrRef } from "../lib/gh.js";
import { gateActions } from "../lib/gate.js";
import { askReplitOnce, type ReplitAskOutcome } from "../lib/replit.js";
import { tagCursorAndDitto, tagReplit } from "../lib/tag.js";

const BOT_LOGIN = "subnet-review-gate";

/**
 * PR actions that start a review turn.
 *
 * `synchronize` is included on purpose: a new head resets every verdict, so it
 * must re-review. A duplicate delivery is harmless because the per-head lock
 * refuses a second review of the same SHA.
 */
const REVIEW_ACTIONS = new Set(["opened", "synchronize", "reopened", "ready_for_review"]);

function refOf(ctx: GitHubEventContext): PrRef {
  return {
    owner: ctx.repository.owner,
    repo: ctx.repository.name,
    number: ctx.conversation.number,
  };
}

/**
 * The head and draft flag, read live.
 *
 * Every hook re-reads this rather than trusting the delivery payload: a hook
 * can fire on a draft, and a draft must never be tagged or reviewed — the
 * reviewer round trip is for a PR that is actually asking for review.
 */
async function readHead(
  ctx: GitHubEventContext,
  ref: PrRef,
): Promise<{ headSha: string; draft: boolean }> {
  const octokit = await ctx.host.github.getOctokit();
  const { data } = await octokit.rest.pulls.get({
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
  });
  return { headSha: data.head.sha, draft: data.draft ?? false };
}

type AdvanceResult = {
  headSha: string;
  draft: boolean;
  next: string;
  needsReviewTurn: boolean;
  taggedCursorDitto: string;
  taggedReplit: string;
  replitAsk: string;
};

/**
 * One structured line for an ask that will not succeed. A silent failure here
 * used to mean Replit was never asked and nobody knew.
 */
function logAsk(outcome: ReplitAskOutcome, prNumber: number, headSha: string): void {
  if (outcome.asked || outcome.reason === "already-asked" || !outcome.persistent) {
    return;
  }
  console.error(
    JSON.stringify({
      level: "error",
      event: "replit_ask_persistent_failure",
      pr: prNumber,
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
async function advanceGate(input: {
  ctx: GitHubEventContext;
  kv: HostKvApi;
  ref: PrRef;
}): Promise<AdvanceResult> {
  const { ctx, kv, ref } = input;
  const octokit = await ctx.host.github.getOctokit();
  const { headSha, draft } = await readHead(ctx, ref);

  if (draft) {
    return {
      headSha,
      draft,
      next: "review",
      needsReviewTurn: false,
      taggedCursorDitto: "skipped:draft",
      taggedReplit: "skipped:draft",
      replitAsk: "skipped:draft",
    };
  }

  const state = await readGateState({ octokit, kv, ref, headSha });
  const actions = gateActions(state, false);

  // The Cursor/Ditto tag is posted on every head, so the round trip starts
  // immediately and does not wait for MC's verdict to be written down.
  let taggedCursorDitto = "skipped";
  if (actions.tagCursorDitto) {
    const tag = await tagCursorAndDitto({ octokit, kv, ref, headSha, state });
    taggedCursorDitto = tag.reason;
  }

  let taggedReplit = "skipped";
  if (actions.tagReplit) {
    const tag = await tagReplit({ octokit, kv, ref, headSha, currentHeadSha: headSha });
    taggedReplit = tag.reason;
  }

  let replitAsk = "skipped";
  if (actions.askReplit) {
    const ask = await askReplitOnce({ kv, mcp: ctx.host.mcp, prNumber: ref.number, headSha });
    logAsk(ask, ref.number, headSha);
    replitAsk = askLabel(ask);
  }

  return {
    headSha,
    draft,
    next: state.next,
    needsReviewTurn: actions.needsReviewTurn,
    taggedCursorDitto,
    taggedReplit,
    replitAsk,
  };
}

export default githubChannel({
  botName: BOT_LOGIN,
  cursorAccount: { repos: ["cryptoreporthub/subnet-dashboard"], permissions: "pr-write" },
  // The bot posts its verdicts through `post_verdict` and its tags through
  // `advanceGate`. The channel must not also echo assistant text onto the PR.
  deliverReplies: false,
  progress: { reactions: false },

  // The catch-all `onEvent` would otherwise advertise every webhook event,
  // including ones outside this PR session's continuation membership
  // (`pull_request_review_thread`), which makes every delivery start a fresh
  // session. Pin the set this gate actually handles.
  webhookEvents: [
    "pull_request",
    "issue_comment",
    "pull_request_review_comment",
    "pull_request_review",
  ],

  onPullRequest: async (ctx, pr) => {
    if (pr.draft || !REVIEW_ACTIONS.has(pr.action)) {
      return null;
    }
    // Tags first, in plain code, so they land even if the model turn fails.
    await advanceGate({ ctx, kv: ctx.host.kv, ref: refOf(ctx) });
    return { auth: defaultGitHubAuth(ctx) };
  },

  /**
   * Review and comment events re-run the gate.
   *
   * Cursor, Ditto and Replit verdicts arrive here. Most of the time the useful
   * work is re-reading the state and posting the next tag; a model turn only
   * runs when MC's own verdict is missing at this head.
   *
   * A comment from this bot is ignored outright — including its own verdict,
   * which is read back from the PR by `readGateState`, not by re-dispatching
   * on the webhook.
   */
  onComment: async (ctx, comment) => {
    if (comment.author?.login === BOT_LOGIN) {
      return null;
    }
    const after = await advanceGate({ ctx, kv: ctx.host.kv, ref: refOf(ctx) });
    return after.needsReviewTurn ? { auth: defaultGitHubAuth(ctx) } : null;
  },

  /**
   * `pull_request_review` has no typed hook and never reaches `onComment`, yet
   * that is where formal verdicts arrive most often. It must not be skipped.
   *
   * `pull_request_review_thread` is deliberately not listed: it is not part of
   * the PR session's continuation membership, and `validate` reports that every
   * delivery on such a channel would start a fresh session. Verdicts arrive on
   * `pull_request_review`, which is in the membership.
   */
  onEvent: async (ctx) => {
    if (ctx.eventName !== "pull_request_review") {
      return null;
    }
    const after = await advanceGate({ ctx, kv: ctx.host.kv, ref: refOf(ctx) });
    return after.needsReviewTurn ? { auth: defaultGitHubAuth(ctx) } : null;
  },
});
