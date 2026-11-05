import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GitHubHandle } from "@grok/agent-sdk/channels/github";
import { prKey, type GateState } from "./gate.js";
import type { PrRef } from "./gh.js";
import { readSuiteRecord, suiteStateFromRecord } from "./gh.js";
import { exclusive } from "./lock.js";

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
    case "needs_joshua":
      return "action_required";
    default: {
      const _exhaustive: never = state.next;
      return _exhaustive;
    }
  }
}

/** One line of facts the check page and the dedupe key share. */
function summaryOf(state: GateState, baseSha: string | undefined): string {
  const baseLine =
    baseSha === undefined || baseSha === "" ? "base missing" : `base ${baseSha.slice(0, 7)}`;
  return [
    `MC ${state.mc}`,
    `Cursor ${state.cursor}`,
    `Ditto ${state.ditto}`,
    state.suite === "needs-joshua" ? `suite NEEDS-JOSHUA (${state.suiteDetail ?? "see the head's suite record"})` : `suite ${state.suite}`,
    `Replit ${state.replit}`,
    baseLine,
    `next: ${state.next}`,
  ].join(" · ");
}

async function readLivePair(octokit: Octokit, ref: PrRef): Promise<{ headSha: string; baseSha: string | undefined }> {
  const { data } = await octokit.rest.pulls.get({ owner: ref.owner, repo: ref.repo, pull_number: ref.number });
  return { headSha: data.head.sha, baseSha: data.base?.sha };
}

async function livePairIs(
  octokit: Octokit,
  ref: PrRef,
  headSha: string,
  baseSha: string | undefined,
): Promise<boolean> {
  const live = await readLivePair(octokit, ref);
  return live.headSha === headSha && live.baseSha === baseSha;
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
  /** The gate this delivery was asked to report. Its head is the check's head. */
  state: GateState;
  /** The gate as it is now, read by the caller. Read again under the lock, never trusted from above. */
  read: () => Promise<GateState>;
  createCheck: CreateCheck;
}): Promise<CheckPost> {
  const { octokit, kv, ref, createCheck, read } = input;
  // One post at a time per head, and the gate is read inside that turn. Two deliveries that
  // overlap would otherwise conclude in whatever order their slow reads finish, so an earlier
  // read could land after a newer one and leave the required check showing a stale verdict.
  // `exclusive` queues callers in this process only; across processes the summary dedupe in kv
  // and the next delivery's post remain the backstop.
  return exclusive(`check:${prKey(ref)}:${input.state.headSha}`, async () => {
    const live = await readLivePair(octokit, ref);
    const state = await read();
    const baseSha = live.baseSha;
    const key = `check:${prKey(ref)}:${state.headSha}:${baseSha ?? "none"}`;
    const summary = summaryOf(state, baseSha);

    if ((await kv.get(key)) === summary) {
      return "unchanged";
    }
    if (live.headSha !== state.headSha) {
      return "stale-head";
    }
    if (baseSha === undefined || baseSha === "") {
      const check = await createCheck({ name: CHECK_NAME, sha: state.headSha });
      await check.conclude({
        conclusion: "action_required",
        output: { title: "Needs Joshua", summary: `${summary} · PR base commit is not available` },
      });
      await kv.put(key, summary);
      return "posted";
    }

    let conclusion = gateConclusion(state);
    if (conclusion === "success") {
      const suite = suiteStateFromRecord(await readSuiteRecord(kv, ref, state.headSha, baseSha));
      if (suite !== "clean" && suite !== "carried") {
        conclusion = "action_required";
      }
    }

    const check = await createCheck({ name: CHECK_NAME, sha: state.headSha });
    const superseded =
      conclusion === "success" && !(await livePairIs(octokit, ref, state.headSha, baseSha));
    if (superseded) {
      await check.conclude({
        conclusion: "cancelled",
        output: {
          title: "Superseded",
          summary: `The PR head or base moved while this was posted, so it is not reported green. ${summary}`,
        },
      });
      return "stale-head";
    }
    const title = state.next === "needs_joshua" ? "Needs Joshua" : titleOf(conclusion);
    await check.conclude({ conclusion, output: { title, summary } });
    await kv.put(key, summary);
    return "posted";
  });
}

function titleOf(conclusion: GateConclusion): string {
  return { success: "Gate passed", failure: "Gate blocked", action_required: "Gate waiting" }[conclusion];
}
