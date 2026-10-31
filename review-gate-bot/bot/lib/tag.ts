import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import {
  cursorDittoTagBody,
  cursorDittoTagKey,
  prKey,
  replitTagBody,
  replitTagKey,
  type GateState,
} from "./gate.js";
import { ranOnce, type RanOnceReason, type RanOnceResult } from "./lock.js";
import { readComments, readGateState, type PrRef } from "./gh.js";
import {
  hasOwnMarker,
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
 * themselves. `hasOwnMarker` checks the author login (the App's bot login)
 * before the marker is believed.
 *
 * Inside one process every post is **exactly once**: `ranOnce` runs callers for
 * a key one at a time, so the second finds the first one's comment. Across
 * processes it is **at most once, best effort**. There is no compare-and-swap on
 * a GitHub comment, so two processes can both pass the "already posted?" read
 * and both post. `postVerdictComment` re-reads immediately before posting to
 * make that window as small as it can be; it does not close it, and nothing
 * here pretends otherwise.
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
  const comments = await readComments(octokit, ref);
  return comments.some((c) => hasOwnMarker(c, slot, headSha));
}

/**
 * May this write still go out for `headSha`? False when the PR has moved off that
 * head, or has turned draft. Asked of GitHub as the last thing before a write. The
 * head a caller passes was read earlier, and reading the gate state is several
 * round trips; a `@cursor review` posted after a push asks for a review of the new
 * head on the strength of a gate decision about the old one. A draft is never
 * tagged, asked about or reviewed, and the PR may have turned draft in that window.
 */
async function isStale(octokit: Octokit, ref: PrRef, headSha: string): Promise<boolean> {
  const { data: pr } = await octokit.rest.pulls.get({ owner: ref.owner, repo: ref.repo, pull_number: ref.number });
  return pr.head.sha !== headSha || pr.draft === true;
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

/** How a `ranOnce` result reads to a caller. Exhaustive over `RanOnceReason`. */
const POST_REASON = {
  ran: "posted",
  "already-done": "already-posted",
  "claim-lost": "claim-lost",
  failed: "claim-lost",
} as const satisfies Record<RanOnceReason, "posted" | "already-posted" | "claim-lost">;

/**
 * Post one marker comment for a head, once, under that slot's lock key.
 *
 * `superseded` means the PR moved off `headSha`, or turned draft, between the gate
 * read and the write, so nothing was posted: a tag for the old head would ask
 * reviewers to look at code that is no longer the PR.
 */
async function postSlotOnce(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  slot: TagSlot;
  key: string;
  body: string;
  /** Re-reads the gate just before the write. The tag's own precondition must still hold, not only the head. */
  stillReady?: () => Promise<boolean>;
}): Promise<{ superseded: boolean; result: RanOnceResult; commentId?: number }> {
  const { octokit, kv, ref, headSha, slot, key, body, stillReady } = input;
  let commentId: number | undefined;
  let superseded = false;
  const result = await ranOnce({
    kv,
    key,
    alreadyDone: () => alreadyPosted(octokit, ref, slot, headSha),
    run: async () => {
      // The gate re-read can take several GitHub calls, during which the PR may move. So the head and draft check
      // comes last: it is the final read before the post.
      if ((stillReady !== undefined && !(await stillReady())) || (await isStale(octokit, ref, headSha))) {
        superseded = true;
        return;
      }
      commentId = await postComment(octokit, ref, `${marker(slot, headSha)}\n${body}`);
    },
  });
  return { superseded, result, commentId };
}

function tagOutcome(
  posted: { superseded: boolean; result: RanOnceResult; commentId?: number },
  next: GateState["next"],
): TagOutcome {
  if (posted.superseded) {
    return { posted: false, reason: "gate-not-ready", next: "blocked" };
  }
  return {
    posted: posted.result.ran,
    reason: POST_REASON[posted.result.reason],
    commentId: posted.commentId,
    next,
  };
}

/**
 * Post exactly one `@cursor review` + `@ditto review` comment for this head.
 *
 * Guarded per `(PR, head SHA)` by its own lock key, separate from the Replit
 * one, so a Replit tag can be posted without suppressing the Cursor/Ditto tag
 * on a later head.
 *
 * `state` is the caller's already-read gate state, so a delivery reads the
 * comment list once for the gate rather than once per post.
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
  const posted = await postSlotOnce({
    octokit,
    kv,
    ref,
    headSha,
    slot: "cursor-ditto",
    key: cursorDittoTagKey(ref, headSha),
    body: cursorDittoTagBody(headSha),
  });
  return tagOutcome(posted, state.next);
}

/**
 * Post `@replit review` once for this head, and only when the gate allows it:
 * MC, Cursor and Ditto all PASS at this head and the suite is clean or carried.
 *
 * The gate is re-read here: this is the one tag whose precondition is the whole
 * gate, so the caller's earlier state is not the authority.
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
  const posted = await postSlotOnce({
    octokit,
    kv,
    ref,
    headSha,
    slot: "replit",
    key: replitTagKey(ref, headSha),
    body: replitTagBody(headSha),
    stillReady: async () => (await readGateState({ octokit, kv, ref, headSha })).next === "tag_replit",
  });
  return tagOutcome(posted, state.next);
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
 * None of that is a compare-and-swap; GitHub has none for comments. Inside one
 * process the claim is exactly once. Across processes it is **at most once,
 * best effort**. A replay never double-posts (guard 3 sees the first comment).
 * A genuine simultaneous cross-process race can still produce two comments, and
 * the gate reads the **latest** marker, so if the two carry different verdicts
 * the later one wins. That is a narrow window, not a harmless one.
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
  let superseded = false;

  const result = await ranOnce({
    kv,
    key: `verdict:${prKey(ref)}:${headSha}`,
    alreadyDone: () => alreadyPosted(octokit, ref, "mc-verdict", headSha),
    run: async () => {
      // Guard 3: re-read once more, immediately before the write.
      if (await alreadyPosted(octokit, ref, "mc-verdict", headSha)) {
        lostToRecheck = true;
        return;
      }
      if (await isStale(octokit, ref, headSha)) {
        superseded = true;
        return;
      }
      commentId = await postComment(octokit, ref, `${marker("mc-verdict", headSha)}\n${body}`);
    },
  });

  if (superseded) {
    return { posted: false, reason: "stale-head" };
  }
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
