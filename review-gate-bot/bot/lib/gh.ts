import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GateInput, GateState, PinnedVerdict, SuiteState } from "./gate.js";
import { computeGate } from "./gate.js";
import type { CommentLike, GateIdentity, ReviewLike } from "./verdicts.js";
import { collectPinnedVerdicts, DEFAULT_IDENTITY, hasOwnMarker } from "./verdicts.js";

export const OWNER = "cryptoreporthub";
export const REPO = "subnet-dashboard";

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
    files: files.map((f) => f.filename),
    url: pr.html_url,
  };
}

/** Head SHA the @replit tag was recorded for in kv, when it was. */
export async function readReplitTaggedFor(kv: HostKvApi, prNumber: number): Promise<string | undefined> {
  const raw = await kv.get(`replit-tag:${prNumber}`);
  if (typeof raw !== "object" || raw === null) {
    return undefined;
  }
  const sha = (raw as { headSha?: unknown }).headSha;
  return typeof sha === "string" ? sha : undefined;
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
  user: { login: string; type?: string } | null;
  performed_via_github_app?: { slug?: string | null } | null;
}): CommentLike {
  return {
    id: raw.id,
    body: raw.body ?? "",
    createdAt: raw.created_at,
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
export function suiteKey(prNumber: number, headSha: string): string {
  return `suite:${prNumber}:${headSha}`;
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
  prNumber: number,
  headSha: string,
): Promise<RecordedSuite | undefined> {
  const raw = await kv.get(suiteKey(prNumber, headSha));
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

export async function readSuiteState(
  kv: HostKvApi,
  prNumber: number,
  headSha: string,
): Promise<SuiteState> {
  return (await readSuiteRecord(kv, prNumber, headSha))?.state ?? "missing";
}

/**
 * Which GitHub identity is this bot actually posting as?
 *
 * The channel authenticates with `cursorAccount`, so the posting login is the
 * GitHub account behind the signed-in Cursor connection — not something that can
 * be read from source. Claude flagged this as the unknown that decides how
 * severe the MC-read-back bug is; hardcoding `subnet-review-gate[bot]` and being
 * wrong would silently make the gate blind to its own verdict again.
 *
 * `GET /user` answers it for the token in hand. The App slug is merged in from
 * `botName`-derived constants, because an App-installed comment carries
 * `performed_via_github_app` and matches on that instead of the login. If the
 * lookup fails the fallback constants are used, so a transient API error
 * degrades to the previous behaviour rather than to "the bot does not recognise
 * itself".
 */
export async function resolveOwnIdentity(octokit: Octokit): Promise<GateIdentity> {
  try {
    const { data } = await octokit.rest.users.getAuthenticated();
    const login = data.login;
    if (login === undefined || login === "") {
      return DEFAULT_IDENTITY;
    }
    return {
      logins: [...new Set([login, ...DEFAULT_IDENTITY.logins])],
      appSlug: DEFAULT_IDENTITY.appSlug,
    };
  } catch {
    return DEFAULT_IDENTITY;
  }
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
  identity?: GateIdentity;
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
    identity: input.identity,
  });
  const verdicts: PinnedVerdict[] = pinned.map((p) => ({
    reviewer: p.reviewer,
    headSha: p.headSha,
    verdict: p.verdict,
  }));

  return computeGate({
    headSha: input.headSha,
    verdicts,
    suite: input.suite,
    replitTaggedForSha: input.replitTaggedForSha,
  });
}

/**
 * Was the @replit tag posted for this head, in these already-read comments?
 *
 * GitHub is the system of record: the tag comment carries
 * `<!-- subnet-review-gate:replit:<sha> -->`, so a tag posted by an earlier
 * process — or by an earlier deployment that has since lost its kv — is still
 * visible. Reading the comment rather than kv-only is what fixes the stall
 * where the tag already existed (posted by another turn, or before a redeploy)
 * and the gate sat on `tag_replit` forever because this process never wrote
 * `replit-tag:<pr>`.
 */
export function replitTaggedIn(
  comments: readonly CommentLike[],
  headSha: string,
  identity: GateIdentity = DEFAULT_IDENTITY,
): string | undefined {
  return comments.some((c) => hasOwnMarker(c, "replit", headSha, identity)) ? headSha : undefined;
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
  const [comments, reviews, identity] = await Promise.all([
    readComments(input.octokit, input.ref),
    readReviews(input.octokit, input.ref),
    resolveOwnIdentity(input.octokit),
  ]);

  const fromGithub = replitTaggedIn(comments, input.headSha, identity);
  const kvTag = await readReplitTaggedFor(input.kv, input.ref.number);

  return gateStateFrom({
    headSha: input.headSha,
    comments,
    reviews,
    identity,
    suite: await readSuiteState(input.kv, input.ref.number, input.headSha),
    replitTaggedForSha: fromGithub ?? kvTag,
  });
}
