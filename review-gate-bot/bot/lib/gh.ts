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
  baseSha: string;
  draft: boolean;
  title: string;
  files: string[];
  url: string;
};

export async function readPr(octokit: Octokit, ref: PrRef): Promise<PrSnapshot> {
  const { data: pr } = await octokit.rest.pulls.get({
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
  });
  const files = await octokit.paginate(octokit.rest.pulls.listFiles, {
    owner: ref.owner,
    repo: ref.repo,
    pull_number: ref.number,
    per_page: 100,
  });
  return {
    number: pr.number,
    headSha: pr.head.sha,
    baseSha: pr.base.sha,
    draft: pr.draft ?? false,
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

/** kv key for the recorded suite result at one head. */
export function suiteKey(ref: PrRef, headSha: string): string {
  return `suite:${prKey(ref)}:${headSha}`;
}

export type RecordedSuite = {
  state: SuiteState;
  newFailures?: string[];
  carriedFrom?: string;
  /** The workflow run the JUnit came from. Absent for a carried result. */
  runId?: number;
  at?: number;
};

/** A recorded suite result, or undefined when this head has none. */
export async function readSuiteRecord(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
): Promise<RecordedSuite | undefined> {
  const raw = await kv.get(suiteKey(ref, headSha));
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

export async function readSuiteState(kv: HostKvApi, ref: PrRef, headSha: string): Promise<SuiteState> {
  return (await readSuiteRecord(kv, ref, headSha))?.state ?? "missing";
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

/** When the tag for this head was posted: the earliest of the bot's own tag comments for it. */
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
  const [comments, reviews] = await Promise.all([
    readComments(input.octokit, input.ref),
    readReviews(input.octokit, input.ref),
  ]);

  return gateStateFrom({
    headSha: input.headSha,
    comments,
    reviews,
    suite: await readSuiteState(input.kv, input.ref, input.headSha),
    replitTaggedForSha: replitTaggedIn(comments, input.headSha),
    replitTaggedAt: replitTagTimeIn(comments, input.headSha),
  });
}
