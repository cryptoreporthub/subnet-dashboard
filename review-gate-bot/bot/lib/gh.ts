import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GateState, PinnedVerdict, SuiteState } from "./gate.js";
import { computeGate, prKey } from "./gate.js";
import type { CommentLike, ReviewLike } from "./verdicts.js";
import { collectPinnedVerdicts, hasOwnMarker, OWNER_LOGIN } from "./verdicts.js";

export type PrRef = { owner: string; repo: string; number: number };

export type PrSnapshot = {
  number: number;
  headSha: string;
  /** Merge-base of head vs base.ref; JUnit compare target. Omitted when GitHub cannot resolve it. */
  baseSha?: string;
  /** Live tip of base.repo@base.ref; suite pair key identity. Omitted when unavailable. */
  baseTipSha?: string;
  draft: boolean;
  title: string;
  files: string[];
  url: string;
};

export type LivePair = {
  headSha: string;
  baseSha: string;
  baseTipSha: string;
  baseRef: string;
  draft: boolean;
};

export const GITHUB_PAIR_READ_DETAIL = "GitHub could not resolve the PR base pair for suite compare";

export function isValidHeadSha(sha: string): boolean {
  return /^[0-9a-f]{40}$/.test(sha);
}

export function pairCompareReady(pair: Pick<LivePair, "headSha" | "baseSha" | "baseTipSha">): boolean {
  return isValidHeadSha(pair.headSha) && pair.baseSha !== "" && pair.baseTipSha !== "";
}

/** After computeGate: never report mergeable when live pair compare fields are missing. */
export function downgradeIfStaleGreen(state: GateState, pair: Pick<LivePair, "headSha" | "baseSha" | "baseTipSha">): GateState {
  if (state.next !== "mergeable") {
    return state;
  }
  if (pairCompareReady(pair)) {
    return state;
  }
  return { ...state, next: "run_suite", suiteDetail: GITHUB_PAIR_READ_DETAIL };
}

/** Head, merge-base, and live base-branch tip. Single source for pair identity and suite compare. */
export async function readLivePair(octokit: Octokit, ref: PrRef, options?: { identityOnly?: boolean }): Promise<LivePair> {
  let headSha = "";
  let draft = false;
  try {
    const { data: pr } = await octokit.rest.pulls.get({
      owner: ref.owner,
      repo: ref.repo,
      pull_number: ref.number,
    });
    headSha = pr.head?.sha ?? "";
    draft = pr.draft ?? false;
    if (!isValidHeadSha(headSha)) {
      return { headSha: "", baseSha: "", baseTipSha: "", baseRef: "", draft };
    }
    const baseRef = pr.base.ref;
    if (baseRef === undefined || baseRef === "") {
      return { headSha, baseSha: "", baseTipSha: "", baseRef: "", draft };
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
    } catch {
      return { headSha, baseSha: "", baseTipSha: "", baseRef, draft };
    }
    if (options?.identityOnly) {
      return { headSha, baseSha: "", baseTipSha, baseRef, draft };
    }
    try {
      const { data: compare } = await octokit.rest.repos.compareCommitsWithBasehead({
        owner: ref.owner,
        repo: ref.repo,
        basehead: `${baseTipSha}...${headSha}`,
      });
      const mergeBase = compare.merge_base_commit?.sha;
      if (mergeBase === undefined || mergeBase === "") {
        return { headSha, baseSha: "", baseTipSha, baseRef, draft };
      }
      return { headSha, baseSha: mergeBase, baseTipSha, baseRef, draft };
    } catch {
      return { headSha, baseSha: "", baseTipSha, baseRef, draft };
    }
  } catch {
    return { headSha: "", baseSha: "", baseTipSha: "", baseRef: "", draft };
  }
}

export async function readPr(octokit: Octokit, ref: PrRef): Promise<PrSnapshot> {
  const pair = await readLivePair(octokit, ref);
  const files = await octokit.paginate(octokit.rest.pulls.listFiles, {
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
    per_page: 100,
  });
  const { data: pr } = await octokit.rest.pulls.get({
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
  });
  return {
    number: pr.number,
    headSha: pair.headSha,
    ...(pair.baseSha !== "" ? { baseSha: pair.baseSha } : {}),
    ...(pair.baseTipSha !== "" ? { baseTipSha: pair.baseTipSha } : {}),
    draft: pair.draft,
    title: pr.title,
    // A rename touches both paths. `x.py` renamed to `x.md` must not look like a
    // prose-only change, so the old path is a changed file too.
    files: [...new Set(files.flatMap((f) => (f.previous_filename === undefined ? [f.filename] : [f.filename, f.previous_filename])))],
    url: pr.html_url,
  };
}

/**
 * Normalize a raw GitHub API payload. Exported so a test can start from the
 * bytes GitHub actually returns and run the whole read path, instead of
 * hand-building the internal shape and skipping the parser.
 */
export function asComment(raw: {
  id: number;
  body?: string | null;
  created_at: string;
  updated_at?: string;
  user: { login: string; type?: string } | null;
  performed_via_github_app?: { id?: number | null; slug?: string | null } | null;
}): CommentLike {
  return {
    id: raw.id,
    body: raw.body ?? "",
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    user: raw.user,
    performedViaGithubApp: raw.performed_via_github_app ?? null,
  };
}

/** Normalize a raw GitHub review payload. Exported for the same reason as `asComment`. */
export function asReview(raw: {
  id: number;
  body?: string | null;
  state: string;
  submitted_at?: string | null;
  commit_id?: string | null;
  user: { login: string; type?: string } | null;
}): ReviewLike {
  return {
    id: raw.id,
    body: raw.body ?? "",
    state: raw.state,
    submittedAt: raw.submitted_at ?? null,
    commitId: raw.commit_id ?? null,
    user: raw.user,
  };
}

export async function readComments(octokit: Octokit, ref: PrRef): Promise<CommentLike[]> {
  const raw = await octokit.paginate(octokit.rest.issues.listComments, {
    owner: ref.owner,
    repo: ref.repo,
    issue_number: ref.number,
    per_page: 100,
  });
  return raw.map(asComment);
}

export async function readReviews(octokit: Octokit, ref: PrRef): Promise<ReviewLike[]> {
  const raw = await octokit.paginate(octokit.rest.pulls.listReviews, {
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
    per_page: 100,
  });
  return raw.map(asReview);
}

/** kv key for the recorded suite result at one head against the live base-branch tip. */
export function suiteKey(ref: PrRef, headSha: string, baseTipSha: string): string {
  return `suite:${prKey(ref)}:${headSha}:${baseTipSha}`;
}

/** Pre–pair-key records and head-only holds (NEEDS-JOSHUA refusals). */
export function legacySuiteKey(ref: PrRef, headSha: string): string {
  return `suite:${prKey(ref)}:${headSha}`;
}

/** Refusals pinned to the head only (`needs-joshua` from suite-definition / diff cap). */
export const SUITE_HEAD_HOLDS = new Set(["needs-joshua"]);

export type RecordedSuite = {
  state: SuiteState;
  newFailures?: string[];
  carriedFrom?: string;
  /** The workflow run the JUnit came from. Absent for a carried result. */
  runId?: number;
  /** Why the comparison is not trusted, and the test IDs behind it. */
  invalid?: string | null;
  missing?: string[];
  skipped?: string[];
  /** Every suite-definition path that made this a NEEDS-JOSHUA refusal. `detail` shows only the first few. */
  definitionFiles?: string[];
  detail?: string;
  at?: number;
};

function parseRecorded(raw: unknown): RecordedSuite | undefined {
  if (typeof raw !== "object" || raw === null) {
    return undefined;
  }
  const record = raw as RecordedSuite;
  const state = record.state;
  if (state !== "clean" && state !== "regressed" && state !== "carried") {
    return undefined;
  }
  return record;
}

function isHeadHold(record: RecordedSuite): boolean {
  return typeof record.invalid === "string" && SUITE_HEAD_HOLDS.has(record.invalid);
}

/**
 * A recorded suite result for this head and live base, or undefined when none applies.
 *
 * Head-only holds are read from the legacy key and outrank a pair-key clean or carried
 * record. Other legacy keys are orphaned and ignored.
 */
export async function readSuiteRecord(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
  baseTipSha: string | undefined,
): Promise<RecordedSuite | undefined> {
  const legacy = parseRecorded(await kv.get(legacySuiteKey(ref, headSha)));
  if (legacy !== undefined && isHeadHold(legacy)) {
    return legacy;
  }
  if (baseTipSha !== undefined) {
    const pair = parseRecorded(await kv.get(suiteKey(ref, headSha, baseTipSha)));
    if (pair !== undefined) {
      return pair;
    }
  }
  return undefined;
}

/** The gate's suite state for a record: NEEDS-JOSHUA is final; pair-key compare invalids stay regressed. */
export function suiteStateFromRecord(record: RecordedSuite | undefined): SuiteState {
  if (record === undefined) {
    return "missing";
  }
  if (record.invalid === "needs-joshua") {
    return "needs-joshua";
  }
  return record.state;
}

function suiteOf(record: RecordedSuite | undefined): SuiteState {
  return suiteStateFromRecord(record);
}

/**
 * Gate reads ignore pair-key clean/carried when the live merge-base is unavailable.
 * Head-only operator NEEDS-JOSHUA and pair-key regressions still apply.
 */
export function gateSuiteRecord(
  record: RecordedSuite | undefined,
  compareReady: boolean,
): RecordedSuite | undefined {
  if (record === undefined) {
    return undefined;
  }
  if (compareReady) {
    return record;
  }
  if (record.invalid === "needs-joshua") {
    return record;
  }
  if (record.state === "clean" || record.state === "carried") {
    return undefined;
  }
  return record;
}

export async function readSuiteState(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
  baseTipSha: string | undefined,
): Promise<SuiteState> {
  return suiteOf(await readSuiteRecord(kv, ref, headSha, baseTipSha));
}

/**
 * The gate state from already-read GitHub data. Pure and exported, so the
 * end-to-end test can run raw API payloads through `asComment` / `asReview`,
 * this function and `computeGate` without stubbing Octokit.
 */
export function gateStateFrom(input: {
  headSha: string;
  comments: readonly CommentLike[];
  reviews: readonly ReviewLike[];
  suite: SuiteState;
  suiteDetail?: string;
  replitTaggedForSha?: string;
  replitTaggedAt?: string;
}): GateState {
  const known = new Set<string>([input.headSha]);
  const resolveSha = (claimed: string): string | undefined => {
    for (const sha of known) {
      if (sha.startsWith(claimed)) {
        return sha;
      }
    }
    return undefined;
  };

  const pinned = collectPinnedVerdicts({
    reviews: input.reviews,
    comments: input.comments,
    resolveSha,
  });
  const verdicts: PinnedVerdict[] = pinned.map((p) => ({
    reviewer: p.reviewer,
    headSha: p.headSha,
    verdict: p.verdict,
    at: p.at,
  }));

  return computeGate({
    headSha: input.headSha,
    verdicts,
    suite: input.suite,
    suiteDetail: input.suiteDetail,
    replitTaggedForSha: input.replitTaggedForSha,
    replitTaggedAt: input.replitTaggedAt,
  });
}

/**
 * Was the @replit tag posted for this head, in these already-read comments?
 *
 * GitHub is the system of record: the tag comment carries
 * `<!-- subnet-review-gate:replit:<sha> -->`, so a tag posted by an earlier
 * process, or before a redeploy, is still visible. Only the comment counts: no
 * kv record stands in for one GitHub does not have.
 */
export function replitTaggedIn(comments: readonly CommentLike[], headSha: string): string | undefined {
  return comments.some((c) => isReplitTag(c, headSha)) ? headSha : undefined;
}

/**
 * A Replit review request for this head: the bot's own tag, or a `@replit review` from Joshua's account that names
 * the head. Joshua's decision (#1513). Another account's tag, or a tag that names another head, is not one.
 */
function isReplitTag(comment: CommentLike, headSha: string): boolean {
  if (hasOwnMarker(comment, "replit", headSha)) {
    return true;
  }
  // Joshua's account only: a comment a GitHub App posted under that login is the App's, not his.
  return (
    comment.user?.login === OWNER_LOGIN &&
    !comment.performedViaGithubApp &&
    /@replit\s+review\b/i.test(comment.body) &&
    comment.body.includes(headSha)
  );
}

/** When the latest Replit request for this head was said (an edit counts): a PASS must come after it. */
export function replitTagTimeIn(comments: readonly CommentLike[], headSha: string): string | undefined {
  // The latest request counts, and an edit is a new request: a PASS must be said after the most recent one.
  const times = comments.filter((c) => isReplitTag(c, headSha)).map(lastRequestTime);
  return times.sort((a, b) => Date.parse(b) - Date.parse(a))[0];
}

function lastRequestTime(comment: CommentLike): string {
  const edited = comment.updatedAt !== undefined && Date.parse(comment.updatedAt) > Date.parse(comment.createdAt);
  return edited ? (comment.updatedAt as string) : comment.createdAt;
}

/**
 * Full gate state for one PR at its current head.
 *
 * Shared by `check_gate_state` (the model asks) and the channel's auto-tagger
 * (plain code decides), so both always agree on the same order.
 */
export async function readGateState(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
}): Promise<GateState> {
  const [comments, reviews, pr] = await Promise.all([
    readComments(input.octokit, input.ref),
    readReviews(input.octokit, input.ref),
    readPr(input.octokit, input.ref),
  ]);

  const baseTipSha = pr.baseTipSha;
  const pairFields = {
    headSha: pr.headSha,
    baseSha: pr.baseSha ?? "",
    baseTipSha: baseTipSha ?? "",
  };
  const compareReady = pairCompareReady(pairFields);
  const rawRecord =
    baseTipSha !== undefined && baseTipSha !== ""
      ? await readSuiteRecord(input.kv, input.ref, input.headSha, baseTipSha)
      : undefined;
  const record = gateSuiteRecord(rawRecord, compareReady);
  const suiteDetail =
    !compareReady &&
    rawRecord !== undefined &&
    (rawRecord.state === "clean" || rawRecord.state === "carried")
      ? GITHUB_PAIR_READ_DETAIL
      : record?.detail;
  const state = gateStateFrom({
    headSha: input.headSha,
    comments,
    reviews,
    suite: suiteOf(record),
    suiteDetail,
    replitTaggedForSha: replitTaggedIn(comments, input.headSha),
    replitTaggedAt: replitTagTimeIn(comments, input.headSha),
  });
  return downgradeIfStaleGreen(state, pairFields);
}
