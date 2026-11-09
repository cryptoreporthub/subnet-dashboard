import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GitHubHandle } from "@grok/agent-sdk/channels/github";
import { checkHoldFingerprint, prKey, type GateState } from "./gate.js";
import type { PrRef } from "./gh.js";
import {
  observePair,
  pairsEqual,
  newDeliveryBudget,
  takeAdmissionRead,
  takeFinalFenceRead,
  takeGithubMutation,
  takeCreateCheck,
  takeRevalidationRead,
  type BaseUnavailable,
  type DeliveryBudget,
  type PairObservation,
  type ReadyPair,
} from "./pair-observation.js";
import { readSuiteRecordTrusted, RECORD_VERSION_MISMATCH_DETAIL } from "./pair-record.js";
import { suiteStateFromRecord, gateSuiteRecord, pairCompareReady, type LivePair } from "./gh.js";
import { exclusive } from "./lock.js";

export const CHECK_NAME = "review-gate";

export const PAIR_UNVERIFIABLE_TITLE = "Pair unverifiable";
export const SUPERSEDED_TITLE = "Superseded";

export type CreateCheck = GitHubHandle["createCheck"];
export type GateCheckHandle = Awaited<ReturnType<CreateCheck>>;

export function checkDedupeKey(
  ref: PrRef,
  headSha: string,
  baseTipSha: string,
  mergeBaseSha: string,
  holdFingerprint: string,
): string {
  return `check:${prKey(ref)}:${headSha}:${baseTipSha}:${mergeBaseSha}:${holdFingerprint}`;
}

export type GateConclusion = "success" | "failure" | "action_required";
export type CheckPost =
  | "posted"
  | "unchanged"
  | "stale-head"
  | "pair-unverifiable"
  | "finalization-unresolved";

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
    case "compare_blocked":
      return "action_required";
    default: {
      const _exhaustive: never = state.next;
      return _exhaustive;
    }
  }
}

export const GITHUB_READ_FAILURE_TITLE = "GitHub read failed";
export const MERGE_BASE_UNAVAILABLE_TITLE = "Merge-base unavailable";

export function summaryOf(state: GateState, baseTipSha: string | undefined): string {
  const baseLine =
    baseTipSha === undefined || baseTipSha === "" ? "base missing" : `base tip ${baseTipSha.slice(0, 7)}`;
  const suiteLine =
    state.suite === "needs-joshua"
      ? `suite NEEDS-JOSHUA (${state.suiteDetail ?? "see the head's suite record"})`
      : state.suite === "regressed" && state.suiteDetail !== undefined && state.suiteDetail !== ""
        ? `suite regressed (${state.suiteDetail})`
        : `suite ${state.suite}`;
  return [`MC ${state.mc}`, `Cursor ${state.cursor}`, `Ditto ${state.ditto}`, suiteLine, `Replit ${state.replit}`, baseLine, `next: ${state.next}`].join(" · ");
}

function terminalSummaryForDedupe(
  state: GateState,
  baseTipSha: string | undefined,
  conclusion: GateConclusion,
): string {
  const summary = summaryOf(state, baseTipSha);
  if (conclusion === "action_required" && state.next === "mergeable") {
    return `${summary} · ${RECORD_VERSION_MISMATCH_DETAIL}`;
  }
  return summary;
}

function requiresInvalidRecordRepost(state: GateState, conclusion: GateConclusion, recordInvalid: boolean): boolean {
  return recordInvalid && conclusion === "action_required" && state.next === "mergeable";
}

/**
 * Whether the terminal check body already on file matches the desired body (byte-identical summary).
 * Used to skip redundant `createCheck` / conclude when coalescing duplicate webhooks.
 */
export async function probeCheckDedupeSnapshot(input: {
  kv: HostKvApi;
  ref: PrRef;
  state: GateState;
  readyPair: ReadyPair;
}): Promise<{ unchanged: boolean }> {
  const { kv, ref, state, readyPair } = input;
  const holdFp = checkHoldFingerprint(state);
  const key = checkDedupeKey(ref, state.headSha, readyPair.baseTipSha, readyPair.mergeBaseSha, holdFp);
  const trusted = await readSuiteRecordTrusted(kv, ref, state.headSha, readyPair.baseTipSha, readyPair);
  const recordInvalid = !trusted.ok;
  let conclusion = gateConclusion(state);
  if (conclusion === "success") {
    const gated = gateSuiteRecord(trusted.ok ? trusted.record : undefined, pairCompareReady(readyAsLive(readyPair)));
    const suite = suiteStateFromRecord(gated);
    if (!trusted.ok || (suite !== "clean" && suite !== "carried")) {
      conclusion = "action_required";
    }
  }
  const desired = terminalSummaryForDedupe(state, readyPair.baseTipSha, conclusion);
  const stored = await kv.get(key);
  if (requiresInvalidRecordRepost(state, conclusion, recordInvalid)) {
    return { unchanged: false };
  }
  return { unchanged: typeof stored === "string" && stored === desired };
}

function readyAsLive(r: ReadyPair): Pick<LivePair, "headSha" | "baseSha" | "baseTipSha"> {
  return { headSha: r.headSha, baseSha: r.mergeBaseSha, baseTipSha: r.baseTipSha };
}

function pairObsSummary(obs: PairObservation): string {
  if (obs.kind === "pair-read-failed") {
    return `${obs.stage}:${obs.code}`;
  }
  if (obs.kind === "base-unavailable") {
    return "merge-base-absent";
  }
  return "ready";
}

function baseUnavailableMatchesExpected(obs: BaseUnavailable, expected: ReadyPair): boolean {
  return (
    obs.prNumber === expected.prNumber &&
    obs.headSha === expected.headSha &&
    obs.baseTipSha === expected.baseTipSha
  );
}

type BaseUnavailableAdmission =
  | { tag: "ready"; obs: ReadyPair }
  | { tag: "post"; baseTipSha: string }
  | { tag: "return"; outcome: CheckPost };

async function resolveBaseUnavailableAdmission(input: {
  admission: BaseUnavailable;
  expected: ReadyPair;
  workingCheck: GateCheckHandle | undefined;
  budget: DeliveryBudget;
  ref: PrRef;
  octokit: Octokit;
}): Promise<BaseUnavailableAdmission> {
  const { admission, expected, workingCheck, budget, ref, octokit } = input;

  const driftOutcome = async (summary: string): Promise<BaseUnavailableAdmission> => {
    if (workingCheck === undefined) {
      return { tag: "return", outcome: "stale-head" };
    }
    const ok = await concludeCancelled(
      workingCheck,
      budget,
      ref,
      { title: SUPERSEDED_TITLE, summary },
      expected,
    );
    return { tag: "return", outcome: ok ? "stale-head" : "finalization-unresolved" };
  };

  if (!baseUnavailableMatchesExpected(admission, expected)) {
    return driftOutcome("Pair drift at admission (base-unavailable).");
  }

  if (!takeRevalidationRead(budget)) {
    if (workingCheck !== undefined) {
      const ok = await concludeCancelled(
        workingCheck,
        budget,
        ref,
        { title: PAIR_UNVERIFIABLE_TITLE, summary: "Revalidation read budget exhausted (base-unavailable)." },
        expected,
      );
      return { tag: "return", outcome: ok ? "pair-unverifiable" : "finalization-unresolved" };
    }
    return { tag: "return", outcome: "pair-unverifiable" };
  }

  const rev = await observePair(octokit, ref);
  if (rev.kind === "ready") {
    if (pairsEqual(rev, expected)) {
      return { tag: "ready", obs: rev };
    }
    return driftOutcome("Pair drift on revalidation (base-unavailable).");
  }
  if (rev.kind === "base-unavailable") {
    if (!baseUnavailableMatchesExpected(rev, expected)) {
      return driftOutcome("Pair drift on revalidation (base-unavailable).");
    }
    return { tag: "post", baseTipSha: rev.baseTipSha };
  }
  if (workingCheck !== undefined) {
    const ok = await concludeCancelled(
      workingCheck,
      budget,
      ref,
      { title: PAIR_UNVERIFIABLE_TITLE, summary: `revalidation · ${pairObsSummary(rev)}` },
      expected,
    );
    return { tag: "return", outcome: ok ? "pair-unverifiable" : "finalization-unresolved" };
  }
  return { tag: "return", outcome: "pair-unverifiable" };
}

async function postMergeBaseUnavailable(input: {
  expected: ReadyPair;
  baseTipSha: string;
  workingCheck: GateCheckHandle | undefined;
  budget: DeliveryBudget;
  ref: PrRef;
  octokit: Octokit;
  read: () => Promise<GateState>;
  createCheck: CreateCheck;
}): Promise<CheckPost> {
  const stateEarly = await input.read();
  if (stateEarly.headSha !== input.expected.headSha) {
    if (input.workingCheck === undefined) {
      return "stale-head";
    }
    const ok = await concludeCancelled(
      input.workingCheck,
      input.budget,
      input.ref,
      { title: SUPERSEDED_TITLE, summary: "Gate state head drift (base-unavailable)." },
      input.expected,
    );
    return ok ? "stale-head" : "finalization-unresolved";
  }

  if (!takeRevalidationRead(input.budget)) {
    if (input.workingCheck !== undefined) {
      const ok = await concludeCancelled(
        input.workingCheck,
        input.budget,
        input.ref,
        { title: PAIR_UNVERIFIABLE_TITLE, summary: "Revalidation read budget exhausted before merge-base post." },
        input.expected,
      );
      return ok ? "pair-unverifiable" : "finalization-unresolved";
    }
    return "pair-unverifiable";
  }

  const live = await observePair(input.octokit, input.ref);
  if (live.kind === "ready") {
    if (input.workingCheck === undefined) {
      return "stale-head";
    }
    const ok = await concludeCancelled(
      input.workingCheck,
      input.budget,
      input.ref,
      {
        title: SUPERSEDED_TITLE,
        summary: pairsEqual(live, input.expected)
          ? "Merge base available before post."
          : "Pair drift before merge-base post.",
      },
      input.expected,
    );
    return ok ? "stale-head" : "finalization-unresolved";
  }
  if (live.kind === "base-unavailable") {
    if (!baseUnavailableMatchesExpected(live, input.expected)) {
      if (input.workingCheck === undefined) {
        return "stale-head";
      }
      const ok = await concludeCancelled(
        input.workingCheck,
        input.budget,
        input.ref,
        { title: SUPERSEDED_TITLE, summary: "Base tip drift before merge-base post." },
        input.expected,
      );
      return ok ? "stale-head" : "finalization-unresolved";
    }
  } else {
    if (input.workingCheck !== undefined) {
      const ok = await concludeCancelled(
        input.workingCheck,
        input.budget,
        input.ref,
        { title: PAIR_UNVERIFIABLE_TITLE, summary: `revalidation · ${pairObsSummary(live)}` },
        input.expected,
      );
      return ok ? "pair-unverifiable" : "finalization-unresolved";
    }
    return "pair-unverifiable";
  }

  const postBaseTipSha = live.kind === "base-unavailable" ? live.baseTipSha : input.baseTipSha;
  const check =
    input.workingCheck ??
    (takeCreateCheck(input.budget)
      ? await input.createCheck({ name: CHECK_NAME, sha: input.expected.headSha })
      : undefined);
  const out = await concludeActionRequiredMergeBase(
    check,
    input.budget,
    input.ref,
    {
      title: MERGE_BASE_UNAVAILABLE_TITLE,
      summary: `${summaryOf(stateEarly, postBaseTipSha)} · merge-base-absent`,
    },
    input.expected,
  );
  return out === "confirmed" ? "posted" : "finalization-unresolved";
}

/** Exported for RD-02 (distinct Compare blocked vs other waiting titles). */
export function terminalTitle(state: GateState, conclusion: GateConclusion): string {
  if (state.next === "needs_joshua") {
    return "Needs Joshua";
  }
  if (state.next === "compare_blocked") {
    return "Compare blocked";
  }
  return { success: "Gate passed", failure: "Gate blocked", action_required: "Gate waiting" }[conclusion];
}

function logGateCheckFailure(
  phase: string,
  ref: PrRef,
  extra?: { expectedPair?: ReadyPair; budget?: DeliveryBudget },
): void {
  const payload: Record<string, unknown> = {
    level: "error",
    event: "gate_check_github_failure",
    phase,
    pr: prKey(ref),
  };
  if (extra?.expectedPair !== undefined) {
    const e = extra.expectedPair;
    payload.expectedPair = {
      head: e.headSha.slice(0, 7),
      baseTip: e.baseTipSha.slice(0, 7),
      mergeBase: e.mergeBaseSha.slice(0, 7),
    };
  }
  if (extra?.budget !== undefined) {
    payload.counters = { ...extra.budget };
  }
  console.error(JSON.stringify(payload));
}

/** Up to two mutation attempts for the same cancel (§9 TC-double-mut-fail). */
async function concludeCancelled(
  handle: GateCheckHandle | undefined,
  budget: DeliveryBudget,
  ref: PrRef,
  output: { title: string; summary: string },
  expectedPair?: ReadyPair,
): Promise<boolean> {
  if (handle === undefined) {
    return false;
  }
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    if (!takeGithubMutation(budget)) {
      logGateCheckFailure(`cancel-mut-${attempt}`, ref, { expectedPair, budget });
      return false;
    }
    try {
      await handle.conclude({ conclusion: "cancelled", output });
      return true;
    } catch {
      logGateCheckFailure(`cancel-attempt-${attempt}`, ref, { expectedPair, budget });
    }
  }
  return false;
}

type TerminalOutcome = "confirmed" | "finalization-unresolved" | "pair-unverifiable" | "stale-head";

/**
 * Non-cancel terminal with revalidation + one retry (§9). Does not write KV.
 * Uses at most two mutation slots after optional revalidation read.
 */
async function concludeNonCancelTerminal(input: {
  handle: GateCheckHandle;
  budget: DeliveryBudget;
  ref: PrRef;
  octokit: Octokit;
  obs: ReadyPair;
  conclusion: GateConclusion;
  output: { title: string; summary: string };
  workingCheck: GateCheckHandle | undefined;
}): Promise<TerminalOutcome> {
  const { handle, budget, ref, octokit, obs, conclusion, output, workingCheck } = input;
  const tryOnce = async (): Promise<boolean> => {
    if (!takeGithubMutation(budget)) {
      logGateCheckFailure("terminal-no-mut", ref, { expectedPair: obs, budget });
      return false;
    }
    try {
      await handle.conclude({ conclusion, output });
      return true;
    } catch {
      logGateCheckFailure("conclude", ref, { expectedPair: obs, budget });
      return false;
    }
  };
  if (await tryOnce()) {
    return "confirmed";
  }
  if (!takeRevalidationRead(budget)) {
    logGateCheckFailure("reval-read-exhausted-after-conclude-fail", ref, { expectedPair: obs, budget });
    return "finalization-unresolved";
  }
  const rev = await observePair(octokit, ref);
  if (rev.kind === "ready" && !pairsEqual(rev, obs)) {
    const h = workingCheck ?? handle;
    const ok = await concludeCancelled(h, budget, ref, { title: SUPERSEDED_TITLE, summary: "Pair drift on revalidation." }, obs);
    return ok ? "stale-head" : "finalization-unresolved";
  }
  if (rev.kind === "ready" && pairsEqual(rev, obs)) {
    if (await tryOnce()) {
      return "confirmed";
    }
    return "finalization-unresolved";
  }
  const ok = await concludeCancelled(
    handle,
    budget,
    ref,
    { title: PAIR_UNVERIFIABLE_TITLE, summary: `revalidation · ${pairObsSummary(rev)}` },
    obs,
  );
  return ok ? "pair-unverifiable" : "finalization-unresolved";
}

async function concludeActionRequiredMergeBase(
  check: GateCheckHandle | undefined,
  budget: DeliveryBudget,
  ref: PrRef,
  output: { title: string; summary: string },
  expectedPair?: ReadyPair,
): Promise<TerminalOutcome> {
  if (check === undefined) {
    return "finalization-unresolved";
  }
  if (!takeGithubMutation(budget)) {
    logGateCheckFailure("base-unavail-no-mut", ref, { expectedPair, budget });
    return "finalization-unresolved";
  }
  try {
    await check.conclude({ conclusion: "action_required", output });
    return "confirmed";
  } catch {
    logGateCheckFailure("base-unavail-conclude", ref, { expectedPair, budget });
    return "finalization-unresolved";
  }
}

export async function openGateCheckWorking(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  baseSha: string;
  baseTipSha: string;
  createCheck: CreateCheck;
  budget: DeliveryBudget;
}): Promise<GateCheckHandle | undefined> {
  const budget = input.budget;
  const expected: ReadyPair = {
    kind: "ready",
    prNumber: input.ref.number,
    headSha: input.headSha,
    baseTipSha: input.baseTipSha,
    mergeBaseSha: input.baseSha,
    draft: false,
    baseRef: "",
  };
  const obs = await observePair(input.octokit, input.ref);
  if (obs.kind !== "ready" || !pairsEqual(obs, expected)) {
    return undefined;
  }
  if (!takeCreateCheck(budget)) {
    return undefined;
  }
  const check = await input.createCheck({ name: CHECK_NAME, sha: input.headSha });
  try {
    // `in_progress` is not a terminal conclude — do not charge terminal mutation budget (plan §5).
    await check.update({
      status: "in_progress",
      output: {
        title: "Gate working",
        summary: `suite compare running · merge-base ${input.baseSha.slice(0, 7)} · base tip ${input.baseTipSha.slice(0, 7)}`,
      },
    });
  } catch {
    // Handle retained for postGateCheck.
  }
  return check;
}

export async function postGateCheck(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  state: GateState;
  read: () => Promise<GateState>;
  createCheck: CreateCheck;
  workingCheck?: GateCheckHandle;
  expectedPair?: ReadyPair;
  deliveryBudget?: DeliveryBudget;
}): Promise<CheckPost> {
  const { octokit, kv, ref, createCheck, read, workingCheck } = input;
  const budget = input.deliveryBudget ?? newDeliveryBudget();
  const expected = input.expectedPair;

  return exclusive(`check:${prKey(ref)}:${input.state.headSha}`, async () => {
    let obs: ReadyPair;

    if (expected !== undefined) {
      if (!takeAdmissionRead(budget)) {
        if (workingCheck !== undefined) {
          const ok = await concludeCancelled(
            workingCheck,
            budget,
            ref,
            { title: PAIR_UNVERIFIABLE_TITLE, summary: "Admission read budget exhausted." },
            expected,
          );
          return ok ? "pair-unverifiable" : "finalization-unresolved";
        }
        return "pair-unverifiable";
      }

      const a1: PairObservation = await observePair(octokit, ref);

      if (a1.kind === "ready" && pairsEqual(a1, expected)) {
        obs = a1;
      } else if (a1.kind === "ready" && !pairsEqual(a1, expected)) {
        if (workingCheck === undefined) {
          return "stale-head";
        }
        const ok = await concludeCancelled(
          workingCheck,
          budget,
          ref,
          { title: SUPERSEDED_TITLE, summary: "Pair drift at admission." },
          expected,
        );
        return ok ? "stale-head" : "finalization-unresolved";
      } else if (a1.kind === "base-unavailable") {
        const resolved = await resolveBaseUnavailableAdmission({
          admission: a1,
          expected,
          workingCheck,
          budget,
          ref,
          octokit,
        });
        if (resolved.tag === "ready") {
          obs = resolved.obs;
        } else if (resolved.tag === "return") {
          return resolved.outcome;
        } else {
          return postMergeBaseUnavailable({
            expected,
            baseTipSha: resolved.baseTipSha,
            workingCheck,
            budget,
            ref,
            octokit,
            read,
            createCheck,
          });
        }
      } else {
        if (takeAdmissionRead(budget)) {
          const a2 = await observePair(octokit, ref);
          if (a2.kind === "ready" && pairsEqual(a2, expected)) {
            obs = a2;
          } else if (a2.kind === "ready" && !pairsEqual(a2, expected)) {
            if (workingCheck === undefined) {
              return "stale-head";
            }
            const ok = await concludeCancelled(
              workingCheck,
              budget,
              ref,
              { title: SUPERSEDED_TITLE, summary: "Pair drift at admission." },
              expected,
            );
            return ok ? "stale-head" : "finalization-unresolved";
          } else if (a2.kind === "base-unavailable") {
            const resolved = await resolveBaseUnavailableAdmission({
              admission: a2,
              expected,
              workingCheck,
              budget,
              ref,
              octokit,
            });
            if (resolved.tag === "ready") {
              obs = resolved.obs;
            } else if (resolved.tag === "return") {
              return resolved.outcome;
            } else {
              return postMergeBaseUnavailable({
                expected,
                baseTipSha: resolved.baseTipSha,
                workingCheck,
                budget,
                ref,
                octokit,
                read,
                createCheck,
              });
            }
          } else {
            if (workingCheck !== undefined) {
              const ok = await concludeCancelled(
                workingCheck,
                budget,
                ref,
                {
                  title: PAIR_UNVERIFIABLE_TITLE,
                  summary: `pair-read-failed · ${pairObsSummary(a2)}`,
                },
                expected,
              );
              return ok ? "pair-unverifiable" : "finalization-unresolved";
            }
            return "pair-unverifiable";
          }
        } else {
          if (workingCheck !== undefined) {
            const ok = await concludeCancelled(
              workingCheck,
              budget,
              ref,
              {
                title: PAIR_UNVERIFIABLE_TITLE,
                summary: `pair-read-failed · ${pairObsSummary(a1)}`,
              },
              expected,
            );
            return ok ? "pair-unverifiable" : "finalization-unresolved";
          }
          return "pair-unverifiable";
        }
      }
    } else {
      if (!takeAdmissionRead(budget)) {
        return workingCheck !== undefined ? "finalization-unresolved" : "pair-unverifiable";
      }
      const a0 = await observePair(octokit, ref);
      if (a0.kind !== "ready") {
        const stateEarly = await read();
        if (a0.kind === "base-unavailable" && a0.headSha !== stateEarly.headSha) {
          if (workingCheck === undefined) {
            return "stale-head";
          }
          const ok = await concludeCancelled(
            workingCheck,
            budget,
            ref,
            { title: SUPERSEDED_TITLE, summary: "Head mismatch." },
          );
          return ok ? "stale-head" : "finalization-unresolved";
        }
        if (a0.kind === "pair-read-failed" && workingCheck !== undefined) {
          const ok = await concludeCancelled(
            workingCheck,
            budget,
            ref,
            {
              title: PAIR_UNVERIFIABLE_TITLE,
              summary: `pair-read-failed · ${pairObsSummary(a0)}`,
            },
          );
          return ok ? "pair-unverifiable" : "finalization-unresolved";
        }
        const tip = a0.kind === "base-unavailable" ? a0.baseTipSha : undefined;
        const title = a0.kind === "base-unavailable" ? MERGE_BASE_UNAVAILABLE_TITLE : GITHUB_READ_FAILURE_TITLE;
        const check =
          workingCheck ?? (takeCreateCheck(budget) ? await createCheck({ name: CHECK_NAME, sha: stateEarly.headSha }) : undefined);
        const out = await concludeActionRequiredMergeBase(
          check,
          budget,
          ref,
          {
            title,
            summary: `${summaryOf(stateEarly, tip)} · ${a0.kind === "pair-read-failed" ? pairObsSummary(a0) : "pair not ready"}`,
          },
        );
        return out === "confirmed" ? "posted" : "finalization-unresolved";
      }
      obs = a0;
    }

    const state = await read();

    if (obs.headSha !== state.headSha) {
      if (workingCheck === undefined) {
        return "stale-head";
      }
      const ok = await concludeCancelled(workingCheck, budget, ref, { title: SUPERSEDED_TITLE, summary: "Head mismatch." }, obs);
      return ok ? "stale-head" : "finalization-unresolved";
    }

    const holdFp = checkHoldFingerprint(state);
    const key = checkDedupeKey(ref, state.headSha, obs.baseTipSha, obs.mergeBaseSha, holdFp);

    let conclusion = gateConclusion(state);
    const trusted = await readSuiteRecordTrusted(kv, ref, state.headSha, obs.baseTipSha, obs);
    const recordInvalid = !trusted.ok;

    if (conclusion === "success") {
      const gated = gateSuiteRecord(trusted.ok ? trusted.record : undefined, pairCompareReady(readyAsLive(obs)));
      const suite = suiteStateFromRecord(gated);
      if (!trusted.ok || (suite !== "clean" && suite !== "carried")) {
        conclusion = "action_required";
      }
    }

    /** Final fence: up to two reads; PairReadFailed may retry once (plan §9). */
    let finalObs: PairObservation | undefined;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (!takeFinalFenceRead(budget)) {
        if (workingCheck !== undefined) {
          const ok = await concludeCancelled(
            workingCheck,
            budget,
            ref,
            {
              title: PAIR_UNVERIFIABLE_TITLE,
              summary: "Final-fence read budget exhausted.",
            },
            obs,
          );
          return ok ? "pair-unverifiable" : "finalization-unresolved";
        }
        return "pair-unverifiable";
      }
      const r = await observePair(octokit, ref);
      finalObs = r;
      if (r.kind === "ready") {
        break;
      }
      if (attempt === 0 && r.kind === "pair-read-failed") {
        continue;
      }
      if (workingCheck !== undefined) {
        const ok = await concludeCancelled(
          workingCheck,
          budget,
          ref,
          {
            title: PAIR_UNVERIFIABLE_TITLE,
            summary: `final-fence · ${pairObsSummary(r)}`,
          },
          obs,
        );
        return ok ? "pair-unverifiable" : "finalization-unresolved";
      }
      return "pair-unverifiable";
    }

    if (finalObs === undefined || finalObs.kind !== "ready") {
      if (workingCheck !== undefined) {
        const ok = await concludeCancelled(
          workingCheck,
          budget,
          ref,
          { title: PAIR_UNVERIFIABLE_TITLE, summary: "Final-fence pair observation exhausted." },
          obs,
        );
        return ok ? "pair-unverifiable" : "finalization-unresolved";
      }
      return "pair-unverifiable";
    }

    if (!pairsEqual(finalObs, obs)) {
      if (workingCheck === undefined) {
        return "stale-head";
      }
      const ok = await concludeCancelled(
        workingCheck,
        budget,
        ref,
        { title: SUPERSEDED_TITLE, summary: "Final-fence pair drift." },
        obs,
      );
      return ok ? "stale-head" : "finalization-unresolved";
    }

    const storedSummary = await kv.get(key);
    const buildOut = (): { title: string; summary: string } => ({
      title: terminalTitle(state, conclusion),
      summary: terminalSummaryForDedupe(state, obs.baseTipSha, conclusion),
    });
    const desiredSummary = buildOut().summary;
    const bodiesMatch = typeof storedSummary === "string" && storedSummary === desiredSummary;

    if (bodiesMatch && !requiresInvalidRecordRepost(state, conclusion, recordInvalid)) {
      return "unchanged";
    }

    if (bodiesMatch && requiresInvalidRecordRepost(state, conclusion, recordInvalid)) {
      const handle = workingCheck ?? (takeCreateCheck(budget) ? await createCheck({ name: CHECK_NAME, sha: state.headSha }) : undefined);
      if (handle === undefined) {
        return "pair-unverifiable";
      }
      const mismatchOut = buildOut();
      const outcome = await concludeNonCancelTerminal({
        handle,
        budget,
        ref,
        octokit,
        obs: finalObs,
        conclusion: "action_required",
        output: mismatchOut,
        workingCheck,
      });
      if (outcome === "confirmed") {
        await kv.put(key, mismatchOut.summary);
        return "posted";
      }
      if (outcome === "stale-head") {
        return "stale-head";
      }
      if (outcome === "pair-unverifiable") {
        return "pair-unverifiable";
      }
      return "finalization-unresolved";
    }

    const check = workingCheck ?? (takeCreateCheck(budget) ? await createCheck({ name: CHECK_NAME, sha: state.headSha }) : undefined);
    if (check === undefined) {
      return "pair-unverifiable";
    }

    const term = await concludeNonCancelTerminal({
      handle: check,
      budget,
      ref,
      octokit,
      obs: finalObs,
      conclusion,
      output: buildOut(),
      workingCheck,
    });
    if (term === "stale-head") {
      return "stale-head";
    }
    if (term === "pair-unverifiable") {
      return "pair-unverifiable";
    }
    if (term !== "confirmed") {
      return "finalization-unresolved";
    }
    const postedOut = buildOut();
    await kv.put(key, postedOut.summary);
    return "posted";
  });
}
