import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import {
  cursorDittoTagBody,
  replitTagBody,
  replitTagKey,
  type GateState,
} from "./gate.js";
import { ranOnce } from "./lock.js";
import { readComments, readGateState, type PrRef } from "./gh.js";

/**
 * Automatic tagging. Nobody tags by hand: the channel hook calls this on
 * `pull_request` opened/synchronize and on review/comment events, and the
 * model calls the same functions through tools.
 *
 * Every post carries a marker naming the slot and the head SHA, so
 * "already posted for this head" is answered by GitHub itself. That is the
 * guarantee a lost kv race cannot break.
 */

export type TagSlot = "mc-verdict" | "cursor-ditto" | "replit";

export function marker(slot: TagSlot, headSha: string): string {
  return `<!-- subnet-review-gate:${slot}:${headSha} -->`;
}

/** Has this bot already posted the given slot for this head? */
export async function alreadyPosted(
  octokit: Octokit,
  ref: PrRef,
  slot: TagSlot,
  headSha: string,
): Promise<boolean> {
  const comments = await readComments(octokit, ref);
  const wanted = marker(slot, headSha);
  return comments.some((c) => c.body.includes(wanted));
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
 */
export async function tagCursorAndDitto(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
}): Promise<TagOutcome> {
  const { octokit, kv, ref, headSha } = input;
  const state = await readGateState({ octokit, kv, ref, headSha });

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

  if (result.ran) {
    await kv.put(`replit-tag:${ref.number}`, { headSha, at: Date.now() });
  }

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
 * Post the bot's own verdict, once per head.
 *
 * The body is written by the model, so this only guards delivery: stale head
 * refused, eval sessions stubbed, duplicates detected by marker.
 */
export async function postVerdictComment(input: {
  octokit: Octokit;
  ref: PrRef;
  headSha: string;
  currentHeadSha: string;
  body: string;
}): Promise<{ posted: boolean; reason: string; commentId?: number }> {
  const { octokit, ref, headSha, currentHeadSha, body } = input;
  if (headSha !== currentHeadSha) {
    return { posted: false, reason: "stale-head" };
  }
  const comments = await readComments(octokit, ref);
  const wanted = marker("mc-verdict", headSha);
  if (comments.some((c) => c.body.includes(wanted))) {
    return { posted: false, reason: "already-posted" };
  }
  const commentId = await postComment(octokit, ref, `${wanted}\n${body}`);
  return { posted: true, reason: "posted", commentId };
}
