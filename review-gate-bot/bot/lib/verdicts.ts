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
 *
 * ## MC's own verdict
 *
 * The gate's own verdict is written by `post_verdict` as a comment carrying
 * `<!-- subnet-review-gate:mc-verdict:<head sha> -->`. It is read back here and
 * nowhere else. Two things are validated before it counts, because a comment
 * body is attacker-controlled input:
 *
 * 1. **The author.** Only this bot's own identities (`GATE_BOT_LOGINS`, or a
 *    comment attributed to `GATE_APP_SLUGS`) may fill a slot. Anyone else who
 *    copies a marker is ignored, which is what stops a stranger from either
 *    forging an MC PASS or suppressing the real one.
 * 2. **The SHA.** The marker names the head it was written for, so an MC
 *    verdict only ever applies to that head and a new head resets it like every
 *    other verdict.
 *
 * A marker-carrying comment is attributed to `mc` only. It can never satisfy
 * the Cursor or Ditto slot, which is the bug that let MC's own PASS be read as
 * a Cursor PASS when the bot posted as `cursor[bot]`.
 *
 * ## What is not a verdict
 *
 * Reviewer prose. A verdict is an explicit `PASS` / `MODIFY` / `FAIL` token on
 * the **first line** of a comment, or a formal review state (`APPROVED`,
 * `CHANGES_REQUESTED`). "not a PASS", "PASS? no", "no PASS yet" and "not
 * approved" are negations and are checked before the token, so prose can never
 * release the gate in the dangerous direction.
 */

export type Verdict = "PASS" | "MODIFY" | "FAIL";

export type ReviewerName = "mc" | "cursor" | "ditto" | "replit";

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

/**
 * The identities this bot can post as.
 *
 * `botName` in `bot/channels/github.ts` is `subnet-review-gate`, and GitHub
 * assigns the `[bot]` suffix to an App installation — a login no human can
 * hold, which is why only the suffixed form is trusted here. The bare
 * `subnet-review-gate` is **not**: a person could register that name and post a
 * copied marker under it.
 *
 * But this channel uses `cursorAccount`, so the actual posting login is whatever
 * GitHub account the signed-in Cursor connection holds — not knowable from
 * source. `resolveOwnIdentity` asks GitHub who the token belongs to
 * (`GET /user`) and merges that in. Without it, the gate would silently stop
 * recognising its own verdict, which is the class of bug this file exists to
 * fix.
 */
export const GATE_BOT_LOGINS: readonly string[] = ["subnet-review-gate[bot]"];
export const GATE_APP_SLUG = "subnet-review-gate";

export type GateIdentity = {
  /** Logins that count as this bot. */
  logins: readonly string[];
  /** App slug that counts as this bot, when the post carries one. */
  appSlug?: string;
};

export const DEFAULT_IDENTITY: GateIdentity = { logins: GATE_BOT_LOGINS, appSlug: GATE_APP_SLUG };

export type MarkerSlot = "mc-verdict" | "cursor-ditto" | "replit";

export function marker(slot: MarkerSlot, headSha: string): string {
  return `<!-- subnet-review-gate:${slot}:${headSha} -->`;
}

export type ParsedMarker = { slot: MarkerSlot; headSha: string };

const MARKER_PATTERN = /<!--\s*subnet-review-gate:([a-z-]+):([0-9a-f]{40})\s*-->/g;

/** Every marker in a body. A body may carry at most the one this bot wrote. */
export function parseMarkers(body: string): ParsedMarker[] {
  const out: ParsedMarker[] = [];
  for (const match of body.matchAll(MARKER_PATTERN)) {
    const slot = match[1];
    const headSha = match[2];
    if ((slot === "mc-verdict" || slot === "cursor-ditto" || slot === "replit") && headSha !== undefined) {
      out.push({ slot, headSha });
    }
  }
  return out;
}

export function appSlug(subject: {
  performedViaGithubApp: { slug?: string | null } | null;
}): string | undefined {
  return subject.performedViaGithubApp?.slug ?? undefined;
}

/**
 * Did this bot post the comment? Author and App attribution are both checked;
 * a marker copied by anyone else is not evidence of anything.
 *
 * **The login is authoritative.** A GitHub login is unique, so a comment whose
 * `user.login` is the account this bot's token belongs to was authored by this
 * bot — even when `performed_via_github_app` names some other App that posted on
 * its behalf. Requiring one specific slug was wrong for the `cursorAccount`
 * deployment, where the App in the attribution is not ours to name; it would
 * have made the gate blind to its own verdict again.
 *
 * The configured App slug is accepted as an alternative, because an
 * App-installed comment can be rendered under a login that is not the App's.
 */
export function isOwnComment(
  comment: CommentLike,
  identity: GateIdentity = DEFAULT_IDENTITY,
): boolean {
  const login = comment.user?.login ?? "";
  if (login !== "" && identity.logins.includes(login)) {
    return true;
  }
  const slug = appSlug(comment);
  return slug !== undefined && identity.appSlug !== undefined && slug === identity.appSlug;
}

/** The head SHA this bot's own marker names for a slot, when the author checks out. */
export function ownMarkerHead(
  comment: CommentLike,
  slot: MarkerSlot,
  identity: GateIdentity = DEFAULT_IDENTITY,
): string | undefined {
  if (!isOwnComment(comment, identity)) {
    return undefined;
  }
  const found = parseMarkers(comment.body).filter((m) => m.slot === slot);
  // More than one marker in one body is not something this bot ever writes.
  return found.length === 1 ? found[0]?.headSha : undefined;
}

/** True when this bot itself posted the given slot for the given head. */
export function hasOwnMarker(
  comment: CommentLike,
  slot: MarkerSlot,
  headSha: string,
  identity: GateIdentity = DEFAULT_IDENTITY,
): boolean {
  return ownMarkerHead(comment, slot, identity) === headSha;
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

/**
 * Phrases that invert a verdict word. Stripped before the token is read, so a
 * negation can never be read as approval.
 */
const NEGATIONS: readonly RegExp[] = [
  /\b(?:PASS|MODIFY|FAIL)\s*\?+\s*,?\s*no\b/gi,
  /\bnot\s+(?:a\s+|an\s+)?(?:PASS|MODIFY|FAIL)\b/gi,
  /\bno\s+(?:PASS|MODIFY|FAIL)\b(?:\s+yet)?/gi,
  /\bnot\s+approved\b/gi,
  /\bno\s+approval\b/gi,
  /\bnot\s+signed\s*off\b/gi,
];

/** The first non-empty, non-marker line: where a verdict token must appear. */
export function firstLine(text: string): string {
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.replace(/<!--[\s\S]*?-->/g, "").trim();
    if (trimmed !== "") {
      return trimmed;
    }
  }
  return "";
}

/**
 * Extract a verdict token from the **first line** of a comment.
 *
 * `PASS`, `MODIFY`, `FAIL`, with optional markdown around them. Tokens later in
 * the body are ignored: "tests FAIL, so overall PASS" states no verdict on its
 * first line, and guessing which of the two words is the verdict is how a gate
 * approves the wrong thing.
 */
export function parseVerdictToken(text: string): Verdict | undefined {
  let line = firstLine(text);
  for (const negation of NEGATIONS) {
    line = line.replace(negation, " ");
  }
  const match = /\b(PASS|MODIFY|FAIL)\b/.exec(line);
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
 * A comment's verdict, from its first-line token only.
 *
 * There is deliberately no prose fallback. "approved" in a paragraph is not a
 * verdict, and reading it as one is a false PASS in the direction that ships
 * code. A reviewer who means PASS writes PASS.
 */
export function verdictFromComment(comment: CommentLike): Verdict | undefined {
  return parseVerdictToken(comment.body);
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

/**
 * An abbreviated SHA, per GitHub's documented rule: lower case, at least 7
 * characters, and never a prefix of something longer.
 *
 * Three fixes over a bare `\b(?:head|at)\s*([0-9a-f]{7,12})`:
 *
 * - `(?:head|at)` was the whole problem. "at defaced" is a sentence fragment
 *   and also a valid 7-character hex run, so it read as a SHA claim. The
 *   keyword is now `head` / `sha` / `commit`, and a bare word only counts when
 *   it is delimited (backticks or quotes) so it is visibly a SHA and not prose.
 * - The length is no longer a 7–12 guess. It is exactly "at least 7", up to the
 *   length where the full-SHA branch takes over, and `(?![0-9a-f])` on both
 *   sides stops a 40-character SHA from being truncated to 39.
 * - `[0-9a-f]`, not `[0-9a-f]` with `/i`: GitHub writes abbreviations in lower
 *   case, and accepting upper case invites a match on an ordinary ALL-CAPS word
 *   like `DEFACED`.
 *
 * A match here is a *claim*, not a verdict. It is resolved against the heads
 * the caller actually knows (see `resolveSha` in `collectPinnedVerdicts`), so a
 * hex-looking word that names no real head is dropped rather than guessed.
 */
const DELIMITED_SHA = /[`'"]([0-9a-f]{7,39})[`'"]/;
const KEYWORD_SHA = /\b(?:head|sha|commit)\b[^\n]{0,3}?[`'"]?([0-9a-f]{7,39})(?![0-9a-f])/;

/** The head SHA a comment claims, when it names one. */
export function shaClaimedByComment(comment: CommentLike): string | undefined {
  const full = /(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])/.exec(comment.body);
  if (full !== null) {
    return full[0];
  }
  const keyword = KEYWORD_SHA.exec(comment.body);
  if (keyword !== null) {
    return keyword[1];
  }
  const delimited = DELIMITED_SHA.exec(comment.body);
  return delimited?.[1];
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
  /** Which identities count as this bot. Defaults to `DEFAULT_IDENTITY`. */
  identity?: GateIdentity;
}): PinnedReviewer[] {
  const out: PinnedReviewer[] = [];
  const identity = input.identity ?? DEFAULT_IDENTITY;

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
    const markers = parseMarkers(comment.body);

    if (markers.length > 0) {
      // A marker means "this came from the gate". Only the gate's own identity
      // may fill a slot, and only the mc-verdict slot is a verdict at all.
      const mcHead = ownMarkerHead(comment, "mc-verdict", identity);
      if (mcHead === undefined) {
        continue;
      }
      const verdict = verdictFromComment(comment);
      if (verdict === undefined) {
        continue;
      }
      out.push({ reviewer: "mc", verdict, headSha: mcHead, sourceId: comment.id, source: "comment" });
      continue;
    }

    const verdict = verdictFromComment(comment);
    if (verdict === undefined) {
      continue;
    }
    let reviewer: ReviewerName | undefined;
    if (isDittoComment(comment)) {
      reviewer = "ditto";
    } else if (comment.user?.login === CURSOR_BOT_LOGIN) {
      reviewer = "cursor";
    } else if (
      comment.user?.login === OWNER_LOGIN &&
      appSlug(comment) === undefined &&
      isReplitReport(comment.body)
    ) {
      // Replit's reports arrive as owner-account prose, pasted in by MC. Only a
      // body that names Replit counts, so Joshua's own `PASS` stays his and is
      // never read as a reviewer verdict. A comment carrying *any* App
      // attribution is not a Replit report: an App comment surfaced under the
      // owner's login could otherwise fill the Replit slot without a review.
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
