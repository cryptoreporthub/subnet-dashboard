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
 * Nothing in this bot acts on a GO, so there is no Joshua check to confuse with
 * Ditto: a Ditto comment is read as Ditto, and no comment is read as a GO.
 *
 * ## MC's own verdict
 *
 * The gate's own verdict is written by `post_verdict` as a comment carrying
 * `<!-- subnet-review-gate:mc-verdict:<head sha> -->`. It is read back here and
 * nowhere else. Two things are validated before it counts, because a comment
 * body is attacker-controlled input:
 *
 * 1. **The author.** Only this bot's own login (`GATE_BOT_LOGIN`), or the
 *    simibot App by its App ID, may fill the MC slot. Anyone else who copies a
 *    marker is ignored, which is what stops a stranger from either forging an
 *    MC PASS or suppressing the real one.
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
 * Reviewer prose. A verdict is an explicit `PASS` / `MODIFY` / `FAIL` token that
 * **opens the first line** of a comment (after an optional heading mark and
 * `Label:`), or a formal review state (`APPROVED`, `CHANGES_REQUESTED`). Any
 * other first line has no verdict. That is an allowlist on purpose: a list of
 * negations ("not a PASS", "Cannot PASS", "~~PASS~~ MODIFY", "Was PASS, now
 * MODIFY"...) can only ever be as long as the phrasings someone has thought of.
 * A PASS whose line goes on to withdraw it ("PASS, not approved") is no PASS.
 * FAIL and MODIFY are never softened by their tail.
 */

export type Verdict = "PASS" | "MODIFY" | "FAIL";

export type ReviewerName = "mc" | "cursor" | "ditto" | "replit";

/** The subset of a GitHub timeline comment this module reads. */
export type CommentLike = {
  id: number;
  body: string;
  createdAt: string;
  /** When the body was last edited. Absent when the source does not say. */
  updatedAt?: string;
  user: { login: string; type?: string } | null;
  performedViaGithubApp: { id?: number | null; slug?: string | null } | null;
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
 * The one identity this bot posts as: its own GitHub App, `simi-revision`.
 *
 * GitHub gives an App installation the `[bot]` suffix, a login no person can
 * hold, so the suffixed form is the whole test. The bare `simi-revision` is
 * **not** trusted: a person could register that name and post a copied marker.
 *
 * `cryptoreporthub` is deliberately not here. MC, Claude, Ditto's relayed
 * comments and Joshua all post from that account, so a marker under it proves
 * nothing about who wrote it. The limit that remains: MC's and Claude's own
 * verdict comments are still only as trustworthy as that shared account.
 */
export const GATE_BOT_LOGIN = "simi-revision[bot]";

/**
 * The Grokbot App, which posts MC verdicts as its own user. The login must match
 * and the comment must carry this App ID. The login alone is a name, and GitHub
 * attributes a comment to its App by ID, so a comment without that attribution
 * is not the App's, whatever its login says.
 */
export const SIMIBOT_LOGIN = "simibot[bot]";
export const SIMIBOT_APP_ID = 5501340;

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

/** Did this bot post the comment? A marker copied by anyone else is not evidence of anything. */
export function isOwnComment(comment: CommentLike): boolean {
  return comment.user?.login === GATE_BOT_LOGIN;
}

/** The head SHA a comment's single marker names for a slot. Author-agnostic: the caller decides whose marker counts. */
function singleMarkerHead(comment: CommentLike, slot: MarkerSlot): string | undefined {
  const found = parseMarkers(comment.body).filter((m) => m.slot === slot);
  // More than one marker in one body is not something this bot ever writes.
  return found.length === 1 ? found[0]?.headSha : undefined;
}

/** The head SHA this bot's own marker names for a slot, when the author checks out. */
export function ownMarkerHead(comment: CommentLike, slot: MarkerSlot): string | undefined {
  return isOwnComment(comment) ? singleMarkerHead(comment, slot) : undefined;
}

/** True when the comment may carry the MC verdict: this bot's own login, or the simibot App by ID. */
export function isMcVerdictAuthor(comment: CommentLike): boolean {
  if (isOwnComment(comment)) {
    return true;
  }
  return comment.user?.login === SIMIBOT_LOGIN && comment.performedViaGithubApp?.id === SIMIBOT_APP_ID;
}

/** True when this bot itself posted the given slot for the given head. */
export function hasOwnMarker(comment: CommentLike, slot: MarkerSlot, headSha: string): boolean {
  return ownMarkerHead(comment, slot) === headSha;
}

/**
 * True when a timeline comment was posted by the Ditto App, as the account it
 * posts as. Measured: the slug arrives with Joshua's login (Ditto acts through
 * his account) or the App's own bot login. The slug under any other login is a
 * stranger who authorised the App, not Ditto.
 */
export function isDittoComment(comment: CommentLike): boolean {
  const login = comment.user?.login;
  return appSlug(comment) === DITTO_APP_SLUG && (login === OWNER_LOGIN || login === DITTO_BOT_LOGIN);
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
 * `PASS` / `MODIFY` / `FAIL` as the opening word of the line, after an optional
 * heading mark, an optional `Label:` of up to 25 letters, and markdown emphasis.
 * `PASS?` is not a verdict, and neither is a token that merely appears.
 */
const VERDICT_LINE =
  /^(?:#{1,6}\s*)?(?:[*_\s]|\p{Extended_Pictographic}\uFE0F?)*(?:[A-Za-z][A-Za-z ]{0,24}:\s*)?[*_`]*(PASS|MODIFY|FAIL)[*_`]*(?![\w?])(.*)$/u;

/** A commit SHA, full or short. */
const SHA_WORD = /^[0-9a-f]{12,40}$/i;

/** A reviewer's `-grokbot` or `-simibot` signature. */
const SIGNATURE_WORD = /^-?(?:grokbot|simibot)$/i;

/**
 * What may follow `PASS` on its first line: an allowlist, and fail closed.
 *
 * Allowed, in this order: an optional head pointer (`at <sha>`, `at head <sha>`,
 * `head <sha>`, or a bare SHA of at least 12 characters, backticked or not), then an
 * optional signature, then trailing punctuation. Nothing else. Twelve characters, because
 * a short run of hex letters is an English word ("effaced", "defaced"). `on` is not a
 * keyword. Returns whether the tail is allowed and the SHA it names, if any.
 */
function passTail(tail: string): { allowed: boolean; sha?: string } {
  const words = tail
    .replace(/[*_`]/g, " ")
    .replace(/[—–,;:]/g, " ")
    .replace(/[.!]+\s*$/, " ")
    .trim()
    .split(/\s+/)
    .filter((word) => word !== "" && word !== "-");
  let i = 0;
  const keyword = words[0]?.toLowerCase();
  if (keyword === "at" && words[1]?.toLowerCase() === "head") {
    i = 2;
  } else if (keyword === "at" || keyword === "head") {
    i = 1;
  }
  let sha: string | undefined;
  if (i > 0) {
    if (!SHA_WORD.test(words[i] ?? "")) {
      return { allowed: false };
    }
    sha = words[i]?.toLowerCase();
    i += 1;
  } else if (SHA_WORD.test(words[0] ?? "")) {
    sha = words[0]?.toLowerCase();
    i = 1;
  }
  if (SIGNATURE_WORD.test(words[i] ?? "")) {
    i += 1;
  }
  return i === words.length ? { allowed: true, sha } : { allowed: false };
}

/** The head SHA a first-line PASS names after itself, when it is an allowed PASS. */
export function namedHeadOnPassLine(text: string): string | undefined {
  const match = VERDICT_LINE.exec(firstLine(text));
  if (match === null || match[1] !== "PASS") {
    return undefined;
  }
  return passTail(match[2] ?? "").sha;
}


/**
 * The verdict a comment's **first line** opens with, if it opens with one.
 *
 * "tests FAIL, so overall PASS" states no verdict, and guessing which of the
 * two words is the verdict is how a gate approves the wrong thing.
 */
export function parseVerdictToken(text: string): Verdict | undefined {
  const line = firstLine(text);
  const match = VERDICT_LINE.exec(line);
  if (match === null) {
    return undefined;
  }
  const verdict = match[1] as Verdict;
  if (verdict === "PASS" && !passTail(match[2] ?? "").allowed) {
    return undefined;
  }
  return verdict;
}

/**
 * A review's own state is the strongest signal; the body is the fallback for a
 * plain comment-style review. A dismissed review was withdrawn and a pending one
 * was never submitted, so neither speaks whatever its body says.
 */
export function verdictFromReview(review: ReviewLike): Verdict | undefined {
  if (review.state === "APPROVED") {
    return "PASS";
  }
  if (review.state === "CHANGES_REQUESTED") {
    return "MODIFY";
  }
  if (review.state === "DISMISSED" || review.state === "PENDING") {
    return undefined;
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
  /** When it was posted. Reviews and comments number separately; time orders them. */
  at: string;
  source: "review" | "comment";
};

/**
 * The head a reviewer comment says it reviewed.
 *
 * A SHA is a claim only when the comment visibly ties it to the head:
 *
 * - **Full (40):** after `head` / `sha` / `commit` (up to 20 characters of
 *   gap, for "head commit was ..."), after `at`, or in backticks or quotes.
 * - **Abbreviated (12-39):** after `head` / `sha` / `commit`, or delimited.
 *   Lower case only, as GitHub writes them. The bare `at` form is not accepted
 *   here: "at defaced" is a sentence fragment and also seven hex characters.
 *   Twelve, not GitHub's seven: seven hex characters is 28 bits, and a PR author
 *   can grind a commit whose SHA starts with the same seven as a stale PASS.
 *
 * A SHA inside a URL, a fenced code block, or a quoted (`>`) line is never a
 * claim. It is evidence the reviewer looked at something, not a statement of
 * which head the verdict is for. A bare 40-character run in prose ("compare
 * <sha> with the earlier run") is not a claim either, which is how a stale PASS
 * that happens to mention the current head used to pin to it.
 *
 * **One head per verdict.** When the comment makes claims for two different
 * commits, it pins to neither. A short and a full form of the same commit
 * (one a prefix of the other) are one claim. A claim is still resolved against
 * the heads the caller knows (see `resolveSha`), so a hex-looking word that
 * names no real head is dropped rather than guessed.
 */
const CLAIM_PATTERNS: readonly RegExp[] = [
  /\b(?:head|sha|commit)\b[^\n]{0,20}?(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])/g,
  /\bat\s+`?([0-9a-f]{40})(?![0-9a-f])/g,
  /[`'"]([0-9a-f]{12,40})[`'"]/g,
  /\b(?:head|sha|commit)\b[^\n]{0,3}?[`'"]?(?<![0-9a-f])([0-9a-f]{12,39})(?![0-9a-f])/g,
];

/** The body with everything that is not the reviewer's own statement removed. */
function statedText(body: string): string {
  return body
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^[ \t]*>.*$/gm, " ")
    .replace(/https?:\/\/\S+/g, " ");
}

/** The head SHA a comment claims, when it names exactly one. */
export function shaClaimedByComment(comment: CommentLike): string | undefined {
  const text = statedText(comment.body);
  const claims = new Set<string>();
  for (const pattern of CLAIM_PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      if (match[1] !== undefined) {
        claims.add(match[1]);
      }
    }
  }
  const longestFirst = [...claims].sort((a, b) => b.length - a.length);
  const distinct = longestFirst.filter((claim, index) => !longestFirst.slice(0, index).some((kept) => kept.startsWith(claim)));
  return distinct.length === 1 ? distinct[0] : undefined;
}

/**
 * Is this owner-account prose a Replit report?
 *
 * Replit's reports are pasted in by MC under the owner's login. The **first
 * line** must open with the name `Replit` and carry the verdict, so a status
 * note that merely mentions Replit ("Replit: not reviewed yet", "still waiting
 * on Replit") is not one.
 */
export function isReplitReport(body: string): boolean {
  const line = firstLine(body);
  return /^(?:#{1,6}\s*)?[*_]*Replit\b/.test(line) && parseVerdictToken(body) !== undefined;
}

/**
 * A first line that names a verdict word but does not parse as one. The parser
 * is an allowlist, so a reviewer who words a verdict in a shape it does not know
 * stalls the gate silently. This makes the stall visible.
 */
function noteUnparsed(comment: CommentLike): void {
  const line = firstLine(comment.body);
  if (/\b(?:PASS|MODIFY|FAIL)\b/.test(line)) {
    console.warn(
      JSON.stringify({
        level: "warn",
        event: "verdict_line_unparsed",
        comment: comment.id,
        author: comment.user?.login ?? null,
        line: line.slice(0, 160),
      }),
    );
  }
}

/** MC's `<!-- mc-verdict:<full sha> -->` marker, as SimiBot writes it. */
const MC_VERDICT_MARKER = /<!--\s*mc-verdict:([0-9a-f]{40})\s*-->/g;

/**
 * The head a SimiBot comment's MC verdict names: the comment must be SimiBot's login and
 * App ID, and carry exactly one such marker. Anything else is no MC verdict.
 */
function simibotMcHead(comment: CommentLike): string | undefined {
  if (comment.user?.login !== SIMIBOT_LOGIN || comment.performedViaGithubApp?.id !== SIMIBOT_APP_ID) {
    return undefined;
  }
  const heads = [...comment.body.matchAll(MC_VERDICT_MARKER)].map((match) => match[1]);
  return heads.length === 1 ? heads[0] : undefined;
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
    out.push({
      reviewer,
      verdict,
      headSha: review.commitId,
      sourceId: review.id,
      at: review.submittedAt ?? "",
      source: "review",
    });
  }

  for (const comment of input.comments) {
    // MC's formal verdict from SimiBot: its App, and one `<!-- mc-verdict:<sha> -->` naming the
    // head. Nobody else's marker counts, and a rejected first line is logged, not dropped.
    const simibotHead = simibotMcHead(comment);
    if (simibotHead !== undefined) {
      const verdict = verdictFromComment(comment);
      const named = namedHeadOnPassLine(comment.body);
      if (verdict === undefined || (named !== undefined && !simibotHead.startsWith(named))) {
        noteUnparsed(comment);
        continue;
      }
      out.push({
        reviewer: "mc",
        verdict,
        headSha: simibotHead,
        sourceId: comment.id,
        at: lastSaid(comment),
        source: "comment",
      });
      continue;
    }

    const markers = parseMarkers(comment.body);

    if (markers.length > 0) {
      // A marker means "this came from the gate". Only the gate's own identity
      // or simibot's App may fill a slot, and only the mc-verdict slot is a
      // verdict at all.
      const mcHead = isMcVerdictAuthor(comment) ? singleMarkerHead(comment, "mc-verdict") : undefined;
      if (mcHead === undefined) {
        continue;
      }
      const verdict = verdictFromComment(comment);
      if (verdict === undefined) {
        continue;
      }
      out.push({
        reviewer: "mc",
        verdict,
        headSha: mcHead,
        sourceId: comment.id,
        at: lastSaid(comment),
        source: "comment",
      });
      continue;
    }

    const verdict = verdictFromComment(comment);
    if (verdict === undefined) {
      noteUnparsed(comment);
      continue;
    }
    let reviewer: ReviewerName | undefined;
    if (isDittoComment(comment)) {
      reviewer = "ditto";
    } else if (comment.user?.login === CURSOR_BOT_LOGIN) {
      reviewer = "cursor";
    } else if (
      comment.user?.login === OWNER_LOGIN &&
      comment.user.type !== "Bot" &&
      comment.performedViaGithubApp === null &&
      isReplitReport(comment.body)
    ) {
      // Replit's reports arrive as owner-account prose, pasted in by MC. Only a
      // first line that opens with Replit counts, so Joshua's own `PASS` stays
      // his and is never read as a reviewer verdict. The comment must carry no
      // App attribution at all (an empty `{}` or `{slug: null}` included) and
      // must not be a bot: another agent posting through the owner's token is
      // not Replit.
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
    out.push({ reviewer, verdict, headSha, sourceId: comment.id, at: lastSaid(comment), source: "comment" });
  }

  // Newest last, so `verdictAt` taking the last match reads "latest wins".
  // Reviews and issue comments are numbered by separate counters, so ids only
  // break a tie between two posts in the same second.
  const time = (value: string): number => {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  };
  return out.sort((a, b) => time(a.at) - time(b.at) || a.sourceId - b.sourceId);
}

/**
 * When a comment last said what it says now. An edit is a new statement: an old
 * comment rewritten after a newer one is the latest word, not the oldest.
 */
function lastSaid(comment: CommentLike): string {
  if (comment.updatedAt === undefined) {
    return comment.createdAt;
  }
  return Date.parse(comment.updatedAt) > Date.parse(comment.createdAt) ? comment.updatedAt : comment.createdAt;
}
