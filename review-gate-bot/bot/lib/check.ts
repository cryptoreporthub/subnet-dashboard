import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GitHubHandle } from "@grok/agent-sdk/channels/github";
import type { GateState } from "./gate.js";
import type { PrRef } from "./gh.js";

/** The merge-box check this bot owns. A branch rule can require it by this name. */
export const CHECK_NAME = "review-gate";

/** `ctx.github.createCheck`, narrowed to what the gate calls. */
export type CreateCheck = GitHubHandle["createCheck"];

export type GateConclusion = "success" | "failure" | "action_required";

/**
 * Green only for a mergeable gate. A FAIL anywhere is red. Everything still
 * waiting on a reviewer, the suite or the tag is `action_required`. GitHub counts
 * neutral and skipped as passing for a required check, so a waiting head must
 * not use either.
 */
export function gateConclusion(state: GateState): GateConclusion {
  switch (state.next) {
    case "mergeable":
      return "success";
    case "blocked":
      return "failure";
    case "review":
    case "await_cursor_ditto":
    case "run_suite":
    case "tag_replit":
    case "await_replit":
      return "action_required";
    default: {
      const _exhaustive: never = state.next;
      return _exhaustive;
    }
  }
}

/** One line of facts the check page and the dedupe key share. */
function summaryOf(state: GateState): string {
  return [
    `MC ${state.mc}`,
    `Cursor ${state.cursor}`,
    `Ditto ${state.ditto}`,
    `suite ${state.suite}`,
    `Replit ${state.replit}`,
    `next: ${state.next}`,
  ].join(" · ");
}

async function headIs(octokit: Octokit, ref: PrRef, headSha: string): Promise<boolean> {
  const { data } = await octokit.rest.pulls.get({ owner: ref.owner, repo: ref.repo, pull_number: ref.number });
  return data.head.sha === headSha;
}

export type CheckPost = "posted" | "unchanged" | "stale-head";

/**
 * Report the gate on the PR head as a `review-gate` check run.
 *
 * - **Stale head never green.** The head is re-read before the run opens, and a
 *   green run is re-checked once more before it concludes. A head that moved
 *   gets no check, or a `cancelled` "superseded" one, never `success`.
 * - **Once per state.** The last posted summary for a head sits in kv; an
 *   identical delivery posts nothing. kv is an optimisation: losing it costs
 *   one duplicate run, never a wrong one.
 * - **A failed post is retried.** The record is written only after the run has
 *   concluded, so the next delivery tries again.
 */
export async function postGateCheck(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  state: GateState;
  createCheck: CreateCheck;
}): Promise<CheckPost> {
  const { octokit, kv, ref, state, createCheck } = input;
  const key = `check:${ref.number}:${state.headSha}`;
  const summary = summaryOf(state);

  if ((await kv.get(key)) === summary) {
    return "unchanged";
  }
  if (!(await headIs(octokit, ref, state.headSha))) {
    return "stale-head";
  }

  const conclusion = gateConclusion(state);
  const check = await createCheck({ name: CHECK_NAME, sha: state.headSha });
  const superseded = conclusion === "success" && !(await headIs(octokit, ref, state.headSha));
  if (superseded) {
    await check.conclude({
      conclusion: "cancelled",
      output: { title: "Superseded", summary: `The PR head moved while this was posted, so it is not reported green. ${summary}` },
    });
    return "stale-head";
  }
  await check.conclude({ conclusion, output: { title: titleOf(conclusion), summary } });
  await kv.put(key, summary);
  return "posted";
}

function titleOf(conclusion: GateConclusion): string {
  return { success: "Gate passed", failure: "Gate blocked", action_required: "Gate waiting" }[conclusion];
}
