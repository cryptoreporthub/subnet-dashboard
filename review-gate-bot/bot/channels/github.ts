import {
  defaultGitHubAuth,
  githubChannel,
  type GitHubEventContext,
} from "@grok/agent-sdk/channels/github";
import { commentTurn, pullRequestTurn, reviewEventTurn, type GateDeps } from "../lib/advance.js";

const BOT_LOGIN = "subnet-review-gate";

async function depsOf(ctx: GitHubEventContext): Promise<GateDeps> {
  return {
    octokit: await ctx.host.github.getOctokit(),
    kv: ctx.host.kv,
    mcp: ctx.host.mcp,
    ref: { owner: ctx.repository.owner, repo: ctx.repository.name, number: ctx.conversation.number },
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

  onPullRequest: async (ctx, pr) =>
    (await pullRequestTurn(await depsOf(ctx), pr)) ? { auth: defaultGitHubAuth(ctx) } : null,

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
  onComment: async (ctx, comment) =>
    (await commentTurn(await depsOf(ctx), comment.author?.login, comment.body)) ? { auth: defaultGitHubAuth(ctx) } : null,

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
    ctx.eventName === "pull_request_review" && (await reviewEventTurn(await depsOf(ctx)))
      ? { auth: defaultGitHubAuth(ctx) }
      : null,
});
