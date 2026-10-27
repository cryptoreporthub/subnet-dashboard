import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { readGateState, resolveOwnIdentity, type PrRef } from "./gh.js";
import { gateActions } from "./gate.js";
import { askReplitOnce, type ReplitAskOutcome } from "./replit.js";
import { tagCursorAndDitto, tagReplit } from "./tag.js";
import { parseMarkers } from "./verdicts.js";

/** What the gate needs from the host: plain handles, so it can run without the SDK. */
export type GateDeps = { octokit: Octokit; kv: HostKvApi; mcp: HostMcpRegistry; ref: PrRef };

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
export async function advanceGate(deps: GateDeps): Promise<AdvanceResult> {
  const { octokit, kv, mcp, ref } = deps;
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
    };
  }

  const state = await readGateState({ octokit, kv, ref, headSha });
  const actions = gateActions(state, false);

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
          pr: ref.number,
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

  // The ask follows the tag, and goes out only if the tag was not refused for a
  // superseded head.
  const replitAsk =
    actions.askReplit && taggedReplit !== "gate-not-ready"
      ? await attempt("ask-replit", async () => {
          const ask = await askReplitOnce({ kv, mcp, prNumber: ref.number, headSha });
          logAsk(ask, ref.number, headSha);
          return askLabel(ask);
        })
      : "skipped";

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
 * Under `cursorAccount` they are authored by a user login, not
 * `subnet-review-gate`, so the login comes from `GET /user`. That login can be
 * `cryptoreporthub`, which is also Joshua, the relayed Replit reports and
 * Ditto's comments, so a login alone drops too much: an own comment must also
 * carry a gate marker, which every tag and verdict the bot posts does.
 *
 * Unverified: when the bot posts as the owner's own account, the marker is the
 * only thing that separates its comments from the owner's. Nothing outside this
 * repo has been checked to confirm what `GET /user` returns for a hosted
 * deployment.
 */
export async function commentTurn(deps: GateDeps, author: string | undefined, body = ""): Promise<boolean> {
  const identity = await resolveOwnIdentity(deps.octokit);
  if (author !== undefined && identity.logins.includes(author) && parseMarkers(body).length > 0) {
    return false;
  }
  return (await advanceGate(deps)).needsReviewTurn;
}

/** `pull_request_review` delivery: does it start a model turn? */
export async function reviewEventTurn(deps: GateDeps): Promise<boolean> {
  return (await advanceGate(deps)).needsReviewTurn;
}
