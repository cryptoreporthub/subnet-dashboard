import type { Octokit } from "@octokit/rest";
import { isValidHeadSha, type PrRef } from "./gh.js";

/** Discriminated PR base pair from GitHub — used on trust paths instead of collapsing failures to empty strings. */

export type ReadyPair = {
  kind: "ready";
  /** From the same `pulls.get` as the pair — avoids a second PR read in trust paths (RD-08). */
  prNumber: number;
  headSha: string;
  baseTipSha: string;
  mergeBaseSha: string;
  draft: boolean;
  baseRef: string;
};

export type BaseUnavailable = {
  kind: "base-unavailable";
  cause: "merge-base-absent";
  prNumber: number;
  headSha: string;
  baseTipSha: string;
  draft: boolean;
  baseRef: string;
};

export type PairReadFailed = {
  kind: "pair-read-failed";
  stage: "pr" | "base-tip" | "compare";
  code: string;
};

export type PairObservation = ReadyPair | BaseUnavailable | PairReadFailed;

/**
 * Allowlisted codes for PairReadFailed (plan §3) — never raw exception text in check summaries.
 * Unknown errors map to `unknown-error`.
 */
const PAIR_ERROR_ALLOWLIST = new Set([
  "invalid-head-sha",
  "missing-base-ref",
  "invalid-base-tip-sha",
  "invalid-merge-base-sha",
  "base-tip-error",
  "compare-error",
  "compare-throw",
  "pr-error",
  "unknown-error",
]);

export function sanitizePairReadCode(stage: PairReadFailed["stage"], raw: string | undefined): string {
  void stage;
  const s = (raw ?? "").trim();
  if (s.length === 0) {
    return "unknown-error";
  }
  const lower = s.toLowerCase();
  if (PAIR_ERROR_ALLOWLIST.has(lower)) {
    return lower;
  }
  if (/^http\s*\d{3}$/i.test(s) || /^\d{3}$/.test(s)) {
    return `http-${s.replace(/\D/g, "").slice(0, 3)}`;
  }
  return "unknown-error";
}

export function pairsEqual(a: ReadyPair, b: ReadyPair): boolean {
  return a.headSha === b.headSha && a.baseTipSha === b.baseTipSha && a.mergeBaseSha === b.mergeBaseSha;
}

export function expectedPairFromStrings(input: {
  headSha: string;
  baseTipSha?: string;
  mergeBaseSha?: string;
}): ReadyPair | undefined {
  const { headSha, baseTipSha = "", mergeBaseSha = "" } = input;
  if (!isValidHeadSha(headSha) || !isValidHeadSha(baseTipSha) || !isValidHeadSha(mergeBaseSha)) {
    return undefined;
  }
  return {
    kind: "ready",
    prNumber: 0,
    headSha,
    baseTipSha,
    mergeBaseSha,
    draft: false,
    baseRef: "",
  };
}

type PullsGetData = Awaited<ReturnType<Octokit["rest"]["pulls"]["get"]>>["data"];

/**
 * Pair observation from an already-fetched `pulls.get` body (one PR read per trust path — RD-08).
 */
export async function observePairFromPull(octokit: Octokit, ref: PrRef, pr: PullsGetData): Promise<PairObservation> {
  const prNumber = pr.number;
  const headSha = pr.head?.sha ?? "";
  const draft = pr.draft ?? false;
  if (!isValidHeadSha(headSha)) {
    return { kind: "pair-read-failed", stage: "pr", code: "invalid-head-sha" };
  }
  const baseRef = pr.base.ref;
  if (baseRef === undefined || baseRef === "") {
    return { kind: "pair-read-failed", stage: "pr", code: "missing-base-ref" };
  }
  const baseOwner = pr.base.repo?.owner?.login ?? ref.owner;
  const baseRepo = pr.base.repo?.name ?? ref.repo;
  let baseTipSha = "";
  try {
    const { data: branch } = await octokit.rest.repos.getBranch({
      owner: baseOwner,
      repo: baseRepo,
      branch: baseRef,
    });
    baseTipSha = branch.commit.sha;
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e);
    return {
      kind: "pair-read-failed",
      stage: "base-tip",
      code: sanitizePairReadCode("base-tip", raw),
    };
  }
  if (!isValidHeadSha(baseTipSha)) {
    return { kind: "pair-read-failed", stage: "base-tip", code: "invalid-base-tip-sha" };
  }
  try {
    const { data: compare } = await octokit.rest.repos.compareCommitsWithBasehead({
      owner: ref.owner,
      repo: ref.repo,
      basehead: `${baseTipSha}...${headSha}`,
    });
    const rawCommit = compare.merge_base_commit;
    if (rawCommit === undefined || rawCommit === null) {
      return {
        kind: "base-unavailable",
        cause: "merge-base-absent",
        prNumber,
        headSha,
        baseTipSha,
        draft,
        baseRef,
      };
    }
    const mergeBase = rawCommit.sha;
    if (mergeBase === undefined || mergeBase === "" || (typeof mergeBase === "string" && mergeBase.trim() === "")) {
      return { kind: "pair-read-failed", stage: "compare", code: "invalid-merge-base-sha" };
    }
    if (!isValidHeadSha(mergeBase)) {
      return { kind: "pair-read-failed", stage: "compare", code: "invalid-merge-base-sha" };
    }
    return {
      kind: "ready",
      prNumber,
      headSha,
      baseTipSha,
      mergeBaseSha: mergeBase,
      draft,
      baseRef,
    };
  } catch {
    return {
      kind: "pair-read-failed",
      stage: "compare",
      code: "compare-throw",
    };
  }
}

/**
 * Single network boundary read: classify ReadyPair vs BaseUnavailable vs PairReadFailed.
 * Does not collapse API failures into BaseUnavailable.
 */
export async function observePair(octokit: Octokit, ref: PrRef): Promise<PairObservation> {
  try {
    const { data: pr } = await octokit.rest.pulls.get({
      owner: ref.owner,
      repo: ref.repo,
      pull_number: ref.number,
    });
    return await observePairFromPull(octokit, ref, pr);
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e);
    return {
      kind: "pair-read-failed",
      stage: "pr",
      code: sanitizePairReadCode("pr", raw),
    };
  }
}

/** Delivery-scoped budgets for reads and GitHub mutations (plan §5). */
export type DeliveryBudget = {
  admissionReads: number;
  finalFenceReads: number;
  revalidationReads: number;
  githubMutations: number;
  createCheckCount: number;
};

let deliveryBudgetFactory: () => DeliveryBudget = () => ({
  admissionReads: 2,
  finalFenceReads: 2,
  revalidationReads: 2,
  githubMutations: 2,
  createCheckCount: 1,
});

/** Tests only: restore default caps after overriding the factory. */
export function resetDeliveryBudgetFactory(): void {
  deliveryBudgetFactory = () => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 2,
    githubMutations: 2,
    createCheckCount: 1,
  });
}

/** Tests only: inject caps for deterministic accounting (§5). */
export function setDeliveryBudgetFactory(factory: () => DeliveryBudget): void {
  deliveryBudgetFactory = factory;
}

export function newDeliveryBudget(): DeliveryBudget {
  return deliveryBudgetFactory();
}

export function takeAdmissionRead(b: DeliveryBudget): boolean {
  if (b.admissionReads <= 0) {
    return false;
  }
  b.admissionReads -= 1;
  return true;
}

export function takeFinalFenceRead(b: DeliveryBudget): boolean {
  if (b.finalFenceReads <= 0) {
    return false;
  }
  b.finalFenceReads -= 1;
  return true;
}

export function takeRevalidationRead(b: DeliveryBudget): boolean {
  if (b.revalidationReads <= 0) {
    return false;
  }
  b.revalidationReads -= 1;
  return true;
}

export function takeGithubMutation(b: DeliveryBudget): boolean {
  if (b.githubMutations <= 0) {
    return false;
  }
  b.githubMutations -= 1;
  return true;
}

export function takeCreateCheck(b: DeliveryBudget): boolean {
  if (b.createCheckCount <= 0) {
    return false;
  }
  b.createCheckCount -= 1;
  return true;
}
