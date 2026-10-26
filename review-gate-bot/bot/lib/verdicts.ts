/**
 * Reading reviewer verdicts back from GitHub, pinned to one head SHA.
 *
 * ## Ditto vs Joshua — the measured field
 *
 * Ditto posts from **Joshua's own account** (`cryptoreporthub`) through the
 * `ditto-code` GitHub App, so `user.login` alone cannot tell a Ditto verdict
 * from a comment Joshua wrote himself. The discriminator is GitHub's
 * `performed_via_github_app` object.
 *
 * Measured on `cryptoreporthub/subnet-dashboard` PR #1515 (2026-10-26):
 *
 * - **Issue/timeline comments** (`GET /repos/{owner}/{repo}/issues/{n}/comments`)
 *   do carry `performed_via_github_app`: `{"slug": "ditto-code", "id": 3889634, ...}`.
 * - **Reviews** (`GET /repos/{owner}/{repo}/pulls/{n}/reviews`) do **not**: the
 *   key is absent entirely (`has("performed_via_github_app") === false`), on
 *   REST and on GraphQL. The author there is `ditto-code[bot]`, the App's bot
 *   identity.
 *
 * So the rule is per-surface, not one field path:
 *
 * | Surface | Ditto when |
 * | --- | --- |
 * | Timeline comment | `comment.performed_via_github_app.slug === "ditto-code"` |
 * | Review | `review.user.login === "ditto-code[bot]"` (no app field exists) |
 * | Anything else from `cryptoreporthub` | **Joshua** |
 *
 * A Ditto verdict is therefore never mistaken for Joshua's GO: the GO check
 * reads the app field first and refuses any comment that carries one.
 */

export type Verdict = "PASS" | "MODIFY" | "FAIL";

export type ReviewerName = "cursor" | "ditto" | "replit";

/** The subset of a GitHub timeline comment this module reads. */
export type CommentLike = {
  id: number;
  body: string;
  createdAt: string;
  user: { login: string; type?: string } | null;
  performedViaGithubApp: { slug?: string | null } | null;
};

/** The subset of a GitHub review this module reads. */
export type ReviewLike = {
  id: number;
  body: string;
  state: string;
  submittedAt: string | null;
  /** `commit_id` — the SHA the review was submitted against. */
  commitId: string | null;
  user: { login: string; type?: string } | null;
  performedViaGithubApp?: { slug?: string | null } | null;
};

export const DITTO_APP_SLUG = "ditto-code";
export const DITTO_BOT_LOGIN = "ditto-code[bot]";
export const CURSOR_BOT_LOGIN = "cursor[bot]";
export const OWNER_LOGIN = "cryptoreporthub";

export function appSlug(subject: {
  performedViaGithubApp: { slug?: string | null } | null;
}): string | undefined {
  return subject.performedViaGithubApp?.slug ?? undefined;
}

/** True when a timeline comment was posted by the Ditto App. */
export function isDittoComment(comment: CommentLike): boolean {
  return appSlug(comment) === DITTO_APP_SLUG;
}

/**
 * True when a review came from Ditto.
 *
 * Reviews carry no `performed_via_github_app` (measured), so the App's bot
 * login is the only signal. It is safe here because the App's identity is
 * fixed and the owner's own reviews arrive as `cryptoreporthub`.
 */
export function isDittoReview(review: ReviewLike): boolean {
  const slug = review.performedViaGithubApp?.slug ?? undefined;
  if (slug !== undefined) {
    return slug === DITTO_APP_SLUG;
  }
  return review.user?.login === DITTO_BOT_LOGIN;
}

/**
 * True when a timeline comment is Joshua acting as himself — the only GO that
 * counts. A comment carrying any App attribution is not Joshua, whichever
 * account it came from.
 */
export function isJoshuaComment(comment: CommentLike): boolean {
  if (appSlug(comment) !== undefined) {
    return false;
  }
  return comment.user?.login === OWNER_LOGIN && comment.user?.type !== "Bot";
}

/** Extract a verdict token. `PASS`, `MODIFY`, `FAIL`, with optional markdown. */
export function parseVerdictToken(text: string): Verdict | undefined {
  const match = /\b(PASS|MODIFY|FAIL)\b/.exec(text);
  if (match === null) {
    return undefined;
  }
  return match[1] as Verdict;
}

/** A review's own state is the strongest signal; the body is the fallback. */
export function verdictFromReview(review: ReviewLike): Verdict | undefined {
  if (review.state === "APPROVED") {
    return "PASS";
  }
  if (review.state === "CHANGES_REQUESTED") {
    return "MODIFY";
  }
  return parseVerdictToken(review.body);
}

/**
 * A Ditto comment states its verdict in prose as often as in a token:
 * "Ditto: approved — no blocking findings in a complete review of b1d28e0."
 * covers the token case and the phrase case, because a real Ditto verdict
 * comment need not spell `PASS`.
 */
export function verdictFromComment(comment: CommentLike): Verdict | undefined {
  const token = parseVerdictToken(comment.body);
  if (token !== undefined) {
    return token;
  }
  if (/\bno blocking findings\b|\bapproved\b/i.test(comment.body)) {
    return "PASS";
  }
  if (/\bchanges requested\b|\bblocking finding/i.test(comment.body)) {
    return "MODIFY";
  }
  return undefined;
}

export type PinnedReviewer = {
  reviewer: ReviewerName;
  verdict: Verdict;
  /** The head SHA the verdict is pinned to, from the review's `commit_id`. */
  headSha: string;
  /** Where it came from, so a reader can check it. */
  sourceId: number;
  source: "review" | "comment";
};

/** The head SHA a comment claims, when it names one. */
export function shaClaimedByComment(comment: CommentLike): string | undefined {
  const full = /\b[0-9a-f]{40}\b/.exec(comment.body);
  if (full !== null) {
    return full[0];
  }
  const short = /\b(?:head|at)\s*`?([0-9a-f]{7,12})`?/i.exec(comment.body);
  return short?.[1];
}

/**
 * Is this owner-account prose a Replit report?
 *
 * The body must name Replit, and must not be one of the gate's own request
 * comments (`@replit review`) or a Ditto/Claude note that merely mentions it.
 */
export function isReplitReport(body: string): boolean {
  if (/^\s*@replit\s+review\b/im.test(body)) {
    return false;
  }
  return /\bReplit\s*:/i.test(body) || /^\s*\**Replit\b[^\n]{0,40}\b(PASS|MODIFY|FAIL)\b/im.test(body);
}

/**
 * Formal reviewer verdicts, each pinned to a head SHA.
 *
 * Cursor and Ditto post both reviews and comments, so both surfaces are read.
 * A verdict with no SHA to pin to is dropped rather than assumed to belong to
 * the current head: an unpinned verdict would let a stale PASS release the
 * gate.
 */
export function collectPinnedVerdicts(input: {
  reviews: readonly ReviewLike[];
  comments: readonly CommentLike[];
  /** Resolve a short SHA claim to a full one, when the caller can. */
  resolveSha?: (claimed: string) => string | undefined;
}): PinnedReviewer[] {
  const out: PinnedReviewer[] = [];

  for (const review of input.reviews) {
    const verdict = verdictFromReview(review);
    if (verdict === undefined) {
      continue;
    }
    let reviewer: ReviewerName | undefined;
    if (isDittoReview(review)) {
      reviewer = "ditto";
    } else if (review.user?.login === CURSOR_BOT_LOGIN) {
      reviewer = "cursor";
    }
    if (reviewer === undefined || review.commitId === null) {
      continue;
    }
    out.push({ reviewer, verdict, headSha: review.commitId, sourceId: review.id, source: "review" });
  }

  for (const comment of input.comments) {
    const verdict = verdictFromComment(comment);
    if (verdict === undefined) {
      continue;
    }
    let reviewer: ReviewerName | undefined;
    if (isDittoComment(comment)) {
      reviewer = "ditto";
    } else if (comment.user?.login === CURSOR_BOT_LOGIN) {
      reviewer = "cursor";
    } else if (comment.user?.login === OWNER_LOGIN && isReplitReport(comment.body)) {
      // Replit's reports arrive as owner-account prose, pasted in by MC. Only a
      // body that names Replit counts, so Joshua's own `PASS` stays his and is
      // never read as a reviewer verdict.
      reviewer = "replit";
    }
    if (reviewer === undefined) {
      continue;
    }
    const claimed = shaClaimedByComment(comment);
    const headSha =
      claimed === undefined
        ? undefined
        : claimed.length === 40
          ? claimed
          : input.resolveSha?.(claimed);
    if (headSha === undefined) {
      continue;
    }
    out.push({ reviewer, verdict, headSha, sourceId: comment.id, source: "comment" });
  }

  // Newest last, so `verdictAt` taking the last match reads "latest wins".
  return out.sort((a, b) => a.sourceId - b.sourceId);
}

/** Does a comment claim a merge/deploy GO? Detection only, never an action. */
export function claimsGo(body: string): boolean {
  return /\b(?:GO|go-ahead|approved to (?:merge|deploy)|cleared to (?:merge|deploy))\b/.test(body);
}
