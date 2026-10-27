import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import {
  cursorDittoTagBody,
  replitTagBody,
  replitTagKey,
  type GateState,
} from "./gate.js";
import { ranOnce } from "./lock.js";
import { readComments, readGateState, resolveOwnIdentity, type PrRef } from "./gh.js";
import {
  hasOwnMarker,
  isOwnComment,
  marker,
  type MarkerSlot,
} from "./verdicts.js";

/**
 * Automatic tagging. Nobody tags by hand: the channel hook calls this on
 * `pull_request` opened/synchronize and on review/comment events, and the
 * model calls the same functions through tools.
 *
 * Every post carries a marker naming the slot and the head SHA, so "already
 * posted for this head" is answered by GitHub itself.
 *
 * **A marker only counts when this bot wrote it.** `body.includes(marker)` over
 * every comment let anyone who can comment — an outside contributor, a random
 * bot — suppress the tag or the verdict for a head by posting the marker text
 * themselves. `hasOwnMarker` checks the author login, and the
 * `performed_via_github_app` slug, before the marker is believed.
 *
 * The concurrency claim is **at most once, best effort**. There is no
 * compare-and-swap on a GitHub comment, so two turns can both pass the
 * "already posted?" read and both post. `postVerdictComment` re-reads
 * immediately before posting to make that window as small as it can be; it
 * does not close it, and nothing here pretends otherwise.
 */

export type TagSlot = MarkerSlot;

export { marker };

/** Has this bot already posted the given slot for this head? */
export async function alreadyPosted(
  octokit: Octokit,
  ref: PrRef,
  slot: TagSlot,
  headSha: string,
): Promise<boolean> {
  const [comments, identity] = await Promise.all([
    readComments(octokit, ref),
    resolveOwnIdentity(octokit),
  ]);
  return comments.some((c) => hasOwnMarker(c, slot, headSha, identity));
}

async function postComment(octokit: Octokit, ref: PrRef, body: string): Promise<number> {
  const { data } = await octokit.rest.issues.createComment({
    owner: ref.owner,
    repo: ref.repo,
    issue_number: ref.number,
    body,
  });
  return data.id;
}

export type TagOutcome = {
  posted: boolean;
  reason: "posted" | "already-posted" | "claim-lost" | "gate-not-ready" | "draft";
  commentId?: number;
  next: GateState["next"];
};

/**
 * Post exactly one `@cursor review` + `@ditto review` comment for this head.
 *
 * Guarded per `(PR, head SHA)` by its own lock key, separate from the Replit
 * one, so a Replit tag can be posted without suppressing the Cursor/Ditto tag
 * on a later head.
 *
 * `state` is the caller's already-read gate state. It used to be re-read here,
 * which meant every delivery fetched the comment list three times (gate state,
 * this, and `alreadyPosted`). The caller has just read it for the same head, so
 * passing it in removes one full paginated read per event.
 */
export async function tagCursorAndDitto(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  /** The gate state the caller just read at `headSha`. */
  state: GateState;
}): Promise<TagOutcome> {
  const { octokit, kv, ref, headSha, state } = input;

  if (state.next === "blocked") {
    return { posted: false, reason: "gate-not-ready", next: state.next };
  }

  let commentId: number | undefined;
  const result = await ranOnce({
    kv,
    key: `tag:${ref.number}:${headSha}:cursor-ditto`,
    alreadyDone: () => alreadyPosted(octokit, ref, "cursor-ditto", headSha),
    run: async () => {
      commentId = await postComment(octokit, ref, `${marker("cursor-ditto", headSha)}\n${cursorDittoTagBody(headSha)}`);
    },
  });

  return {
    posted: result.ran,
    reason:
      result.reason === "ran"
        ? "posted"
        : result.reason === "already-done"
          ? "already-posted"
          : "claim-lost",
    commentId,
    next: state.next,
  };
}

/**
 * Post `@replit review` once for this head, and only when the gate allows it:
 * MC, Cursor and Ditto all PASS at this head and the suite is clean or carried.
 *
 * The gate state is passed in for the same reason as `tagCursorAndDitto`, and
 * the `next !== "tag_replit"` check is repeated here because this function is
 * also reachable from a tool, where the caller's state is not the authority.
 */
export async function tagReplit(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  /** The head the caller just read. A mismatch means a stale caller. */
  currentHeadSha: string;
}): Promise<TagOutcome> {
  const { octokit, kv, ref, headSha, currentHeadSha } = input;

  if (headSha !== currentHeadSha) {
    return { posted: false, reason: "gate-not-ready", next: "blocked" };
  }

  const state = await readGateState({ octokit, kv, ref, headSha });
  if (state.next !== "tag_replit") {
    return { posted: false, reason: "gate-not-ready", next: state.next };
  }

  let commentId: number | undefined;
  const result = await ranOnce({
    kv,
    key: replitTagKey(ref.number, headSha),
    alreadyDone: () => alreadyPosted(octokit, ref, "replit", headSha),
    run: async () => {
      commentId = await postComment(octokit, ref, `${marker("replit", headSha)}\n${replitTagBody(headSha)}`);
    },
  });

  return {
    posted: result.ran,
    reason:
      result.reason === "ran"
        ? "posted"
        : result.reason === "already-done"
          ? "already-posted"
          : "claim-lost",
    commentId,
    next: state.next,
  };
}

export type VerdictPost = {
  posted: boolean;
  reason: "posted" | "already-posted" | "stale-head" | "claim-lost";
  commentId?: number;
};

/**
 * Post the bot's own verdict, at most once per head, best effort.
 *
 * Three guards, in order:
 *
 * 1. **Stale head refused** against the SHA the caller just re-read from
 *    GitHub, not against one read earlier in the turn.
 * 2. **A kv claim** through `ranOnce`, so two turns in different processes
 *    usually agree on which one posts.
 * 3. **A re-read of the PR's comments as the last thing before the post.** This
 *    is the one that matters: the check and the `createComment` call are
 *    adjacent, so the window between them is a single HTTP round trip.
 *
 * None of that is a compare-and-swap; GitHub has none for comments. **At most
 * once, best effort** is the claim. A replay never double-posts (guard 3 sees
 * the first comment). A genuine simultaneous race can still produce two
 * comments — the marker makes the second harmful to nothing, because the gate
 * reads whichever carries it.
 */
export async function postVerdictComment(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  currentHeadSha: string;
  body: string;
}): Promise<VerdictPost> {
  const { octokit, kv, ref, headSha, currentHeadSha, body } = input;
  if (headSha !== currentHeadSha) {
    return { posted: false, reason: "stale-head" };
  }

  let commentId: number | undefined;
  let lostToRecheck = false;

  const result = await ranOnce({
    kv,
    key: `verdict:${ref.number}:${headSha}`,
    alreadyDone: () => alreadyPosted(octokit, ref, "mc-verdict", headSha),
    run: async () => {
      // Guard 3: re-read once more, immediately before the write.
      if (await alreadyPosted(octokit, ref, "mc-verdict", headSha)) {
        lostToRecheck = true;
        return;
      }
      commentId = await postComment(octokit, ref, `${marker("mc-verdict", headSha)}\n${body}`);
    },
  });

  if (lostToRecheck) {
    // Another turn posted between the claim and the write. Its comment is the
    // verdict; this one is a no-op, and the kv claim it holds is released by the
    // next call seeing `alreadyDone`.
    return { posted: false, reason: "already-posted" };
  }
  if (result.ran) {
    return { posted: true, reason: "posted", commentId };
  }
  return {
    posted: false,
    reason: result.reason === "already-done" ? "already-posted" : "claim-lost",
    commentId,
  };
}

/** True when this identity is the gate itself. Re-exported for callers that filter. */
export { isOwnComment };
