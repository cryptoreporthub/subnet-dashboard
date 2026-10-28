import { parseGitHubPrContinuationKey } from "@grok/agent-sdk/channels/github";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { defineHook } from "@grok/agent-sdk/hooks";
import { failureReleasesLease, releaseReviewTurnIfHolder, reviewLeaseFromState } from "../lib/advance.js";

/**
 * A review turn that fails gives its own lease back, and no other.
 *
 * The turn's lease travels in its channel state (the `state` the channel returned with `{ auth }`),
 * not in the prompt, so neither the model nor a commenter can read or forge it. `channelState` is
 * the snapshot taken for this turn, so an overlapping turn cannot overwrite it. The release
 * compares the stored token with this turn's token, and frees the lease only when they match.
 *
 * A `cancelled` turn was stopped or preempted, and a replacement may be running: it keeps its
 * lease. A missing or malformed state releases nothing, and the lease runs out on its TTL.
 */
/** Release the lease this turn carries, if it still holds it. Shared by the failed and the completed paths. */
async function releaseOwnLease(ctx: {
  session: { purpose?: string; continuationKey?: string | null };
  channelState?: unknown;
  host: { kv: HostKvApi };
}) {
  if (ctx.session.purpose === "eval") {
    return;
  }
  const lease = reviewLeaseFromState(ctx.channelState);
  if (lease === undefined) {
    return;
  }
  const ref = parseGitHubPrContinuationKey(ctx.session.continuationKey ?? "");
  if (ref === undefined) {
    return;
  }
  await releaseReviewTurnIfHolder(ctx.host.kv, ref, lease);
}

export default defineHook({
  events: {
    async "turn.failed"(event, ctx) {
      if (!failureReleasesLease(event.data.status)) {
        return;
      }
      await releaseOwnLease(ctx);
    },
    // A turn that completes without posting an MC verdict would otherwise hold its lease until the TTL, and
    // every delivery for that head would wait. Joshua's decision (#1513): release it at once. If the verdict
    // was posted, the gate needs no new turn, so the release changes nothing.
    async "turn.completed"(_event, ctx) {
      await releaseOwnLease(ctx);
    },
  },
});
