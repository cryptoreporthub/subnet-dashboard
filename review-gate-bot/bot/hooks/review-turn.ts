import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import { defineHook } from "@grok/agent-sdk/hooks";
import { releaseReviewTurn } from "../lib/advance.js";

/**
 * A review turn that fails or is cancelled gives its lease back. Without this, a failed
 * turn held `needsReviewTurn: false` for the whole lease TTL, and nothing retried on a timer.
 *
 * The PR comes from the session's continuation key, which is routing, not identity: it names
 * only which PR's lease to free, never who may act. A re-keyed session can free the wrong
 * PR's lease, which costs one extra model turn at most.
 */
export default defineHook({
  events: {
    async "turn.failed"(_event, ctx) {
      if (ctx.session.purpose === "eval") {
        return;
      }
      const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
      if (ref === undefined) {
        return;
      }
      const octokit = await ctx.host.github.getOctokit();
      const { data } = await octokit.rest.pulls.get({ owner: ref.owner, repo: ref.repo, pull_number: ref.number });
      await releaseReviewTurn(ctx.host.kv, ref, data.head.sha);
    },
  },
});
