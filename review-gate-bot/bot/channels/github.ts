import {
  defaultGitHubAuth,
  githubChannel,
  type GitHubEventContext,
} from "@grok/agent-sdk/channels/github";
import { commentReviewTurn, pullRequestReviewTurn, reviewEventReviewTurn, type GateDeps, type ReviewTurnLease } from "../lib/advance.js";

async function depsOf(ctx: GitHubEventContext): Promise<GateDeps> {
  return {
    octokit: await ctx.host.github.getOctokit(),
    kv: ctx.host.kv,
    mcp: ctx.host.mcp,
    ref: { owner: ctx.repository.owner, repo: ctx.repository.name, number: ctx.conversation.number },
    createCheck: (input) => ctx.github.createCheck(input),
  };
}

/**
 * The bot posts as its own GitHub App, `simi-revision`, so its comments carry a
 * login (`simi-revision[bot]`) that nobody else holds. The credentials are
 * named, never read: they are the deployment secrets of the same names, set by
 * Joshua with `agent-sdk secret set`. Events arrive as signed webhooks from the
 * App, which the platform verifies against `GITHUB_WEBHOOK_SECRET`.
 */
/**
 * The turn a delivery starts: `{ auth }` as before, plus the lease the turn holds in its channel
 * state. The lease travels with the turn and is read back by the failure hook, so it never goes
 * into the prompt. No lease means no turn.
 */
function turnFor(ctx: Parameters<typeof defaultGitHubAuth>[0], lease: ReviewTurnLease | undefined) {
  if (lease === undefined) {
    return null;
  }
  return { auth: defaultGitHubAuth(ctx), state: { reviewLease: { head: lease.head, token: lease.token } } };
}

export default githubChannel({
  botName: "simi-revision",
  credentials: {
    appId: { secretName: "GITHUB_APP_ID" },
    privateKey: { secretName: "GITHUB_APP_PRIVATE_KEY" },
    webhookSecret: { secretName: "GITHUB_WEBHOOK_SECRET" },
  },
  // The gate posts its own `review-gate` check run (`lib/check.ts`) through
  // `ctx.github.createCheck`. The flag grants access; it posts nothing itself.
  checks: true,
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

  onPullRequest: async (ctx, pr) => turnFor(ctx, await pullRequestReviewTurn(await depsOf(ctx), pr)),

  /**
   * Review and comment events re-run the gate.
   *
   * Cursor, Ditto and Replit verdicts arrive here. Most of the time the useful
   * work is re-reading the state and posting the next tag; a model turn only
   * runs when MC's own verdict is missing at this head.
   *
   * A comment from this bot is ignored outright, including its own verdict,
   * which is read back from the PR by `readGateState`, not by re-dispatching
   * on the webhook.
   */
  onComment: async (ctx, comment) =>
    turnFor(ctx, await commentReviewTurn(await depsOf(ctx), comment.author?.login)),

  /**
   * `pull_request_review` has no typed hook and never reaches `onComment`, yet
   * that is where formal verdicts arrive most often. It must not be skipped.
   *
   * `pull_request_review_thread` is deliberately not listed: it is not part of
   * the PR session's continuation membership, and `validate` reports that every
   * delivery on such a channel would start a fresh session. Verdicts arrive on
   * `pull_request_review`, which is in the membership.
   */
  onEvent: async (ctx) =>
    ctx.eventName === "pull_request_review" ? turnFor(ctx, await reviewEventReviewTurn(await depsOf(ctx))) : null,
});
