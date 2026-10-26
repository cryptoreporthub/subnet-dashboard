import {
  defaultGitHubAuth,
  githubChannel,
  type GitHubEventContext,
} from "@grok/agent-sdk/channels/github";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { readGateState, type PrRef } from "../lib/gh.js";
import { askReplitOnce } from "../lib/replit.js";
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

type AdvanceResult = {
  headSha: string;
  next: string;
  needsReviewTurn: boolean;
  taggedCursorDitto: string;
  taggedReplit: string;
  replitAsk: string;
};

/**
 * Re-read the gate for the PR's current head and post whatever tags it allows.
 *
 * No model turn and no judgement: `lib/gate.ts` decides, this only delivers.
 * Every post is lock-guarded per head, so a replay or a duplicate webhook runs
 * this again without repeating a comment.
 */
async function advanceGate(input: {
  ctx: GitHubEventContext;
  kv: HostKvApi;
  ref: PrRef;
}): Promise<AdvanceResult> {
  const { ctx, kv, ref } = input;
  const octokit = await ctx.host.github.getOctokit();
  const { data: pr } = await octokit.rest.pulls.get({
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
  });
  const headSha = pr.head.sha;

  const state = await readGateState({ octokit, kv, ref, headSha });

  // The Cursor/Ditto tag is posted on every head, so the round trip starts
  // immediately and does not wait for MC's verdict to be written down.
  let taggedCursorDitto = "skipped";
  if (state.next !== "blocked") {
    const tag = await tagCursorAndDitto({ octokit, kv, ref, headSha });
    taggedCursorDitto = tag.reason;
  }

  let taggedReplit = "skipped";
  let replitAsk = "skipped";

  if (state.next === "tag_replit") {
    const tag = await tagReplit({ octokit, kv, ref, headSha, currentHeadSha: headSha });
    taggedReplit = tag.reason;

    // The Replit MCP step runs only after the tag landed (now or earlier).
    if (tag.posted || tag.reason === "already-posted") {
      const ask = await askReplitOnce({
        kv,
        mcp: ctx.host.mcp,
        prNumber: ref.number,
        headSha,
      });
      replitAsk = ask.asked ? "asked" : ask.reason;
    }
  }

  return {
    headSha,
    next: state.next,
    // A head with no MC verdict is the only reason to spend a model turn.
    needsReviewTurn: state.next === "review",
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
