import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { GateInput, GateState, PinnedVerdict, SuiteState } from "./gate.js";
import { computeGate } from "./gate.js";
import type { CommentLike, ReviewLike } from "./verdicts.js";
import { collectPinnedVerdicts } from "./verdicts.js";

export const OWNER = "cryptoreporthub";
export const REPO = "subnet-dashboard";

/** Marker on every comment this bot posts, so a duplicate is detectable. */
export const BOT_MARKER = "<!-- subnet-review-gate -->";

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

/**
 * GitHub returns `performed_via_github_app` on timeline comments under the
 * snake_case key and `null` when no App was involved. Normalize it so the
 * pure verdict parser never sees a raw payload.
 */
function asComment(raw: {
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

function asReview(raw: {
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
  at?: number;
};

export async function readSuiteState(
  kv: HostKvApi,
  prNumber: number,
  headSha: string,
): Promise<SuiteState> {
  const raw = await kv.get(suiteKey(prNumber, headSha));
  if (typeof raw !== "object" || raw === null) {
    return "missing";
  }
  const state = (raw as RecordedSuite).state;
  return state === "clean" || state === "regressed" || state === "carried" ? state : "missing";
}

/** Head SHA the @replit tag was recorded for, when it was. */
export async function readReplitTaggedFor(kv: HostKvApi, prNumber: number): Promise<string | undefined> {
  const raw = await kv.get(`replit-tag:${prNumber}`);
  if (typeof raw !== "object" || raw === null) {
    return undefined;
  }
  const sha = (raw as { headSha?: unknown }).headSha;
  return typeof sha === "string" ? sha : undefined;
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

  const known = new Set<string>([input.headSha]);
  const resolveSha = (claimed: string): string | undefined => {
    for (const sha of known) {
      if (sha.startsWith(claimed)) {
        return sha;
      }
    }
    return undefined;
  };

  const pinned = collectPinnedVerdicts({ reviews, comments, resolveSha });
  const verdicts: PinnedVerdict[] = pinned.map((p) => ({
    reviewer: p.reviewer,
    headSha: p.headSha,
    verdict: p.verdict,
  }));

  const gateInput: GateInput = {
    headSha: input.headSha,
    verdicts,
    suite: await readSuiteState(input.kv, input.ref.number, input.headSha),
    replitTaggedForSha: await readReplitTaggedFor(input.kv, input.ref.number),
  };
  return computeGate(gateInput);
}
