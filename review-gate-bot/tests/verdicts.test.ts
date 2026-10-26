import assert from "node:assert/strict";
import test from "node:test";
import {
  collectPinnedVerdicts,
  isDittoComment,
  isDittoReview,
  isJoshuaComment,
  verdictFromReview,
  type CommentLike,
  type ReviewLike,
} from "../bot/lib/verdicts.js";

const HEAD = "e4eae96b5ae45b7807abf440d162c21f322f4ae0";

function comment(overrides: Partial<CommentLike> = {}): CommentLike {
  return {
    id: 1,
    body: "MC: **PASS** at `" + HEAD + "`",
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performedViaGithubApp: null,
    ...overrides,
  };
}

function review(overrides: Partial<ReviewLike> = {}): ReviewLike {
  return {
    id: 10,
    body: "Ditto: approved — no blocking findings",
    state: "COMMENTED",
    submittedAt: "2026-10-26T04:00:00Z",
    commitId: HEAD,
    user: { login: "ditto-code[bot]", type: "Bot" },
    ...overrides,
  };
}

test("a timeline comment from the ditto-code App is a Ditto verdict", () => {
  const c = comment({
    user: { login: "ditto-code[bot]", type: "Bot" },
    performedViaGithubApp: { slug: "ditto-code" },
  });
  assert.equal(isDittoComment(c), true);
  assert.equal(isJoshuaComment(c), false);
});

test("a Ditto-App comment posted under Joshua's account is Ditto, not Joshua", () => {
  const c = comment({ user: { login: "cryptoreporthub", type: "User" }, performedViaGithubApp: { slug: "ditto-code" } });
  assert.equal(isDittoComment(c), true);
  assert.equal(isJoshuaComment(c), false);
});

test("a plain owner-account comment is Joshua", () => {
  const c = comment();
  assert.equal(isJoshuaComment(c), true);
  assert.equal(isDittoComment(c), false);
});

test("a review carries no app field, so the bot login identifies Ditto", () => {
  // Measured: GET /pulls/1515/reviews has no `performed_via_github_app` key at
  // all. The parser must still identify Ditto from the App's bot login.
  const r = review({ performedViaGithubApp: undefined });
  assert.equal(isDittoReview(r), true);
  assert.equal(isDittoReview(review({ user: { login: "cursor[bot]", type: "Bot" }, performedViaGithubApp: undefined })), false);
});

test("an owner review with no app attribution is not Ditto", () => {
  const r = review({ user: { login: "cryptoreporthub", type: "User" }, performedViaGithubApp: undefined });
  assert.equal(isDittoReview(r), false);
});

test("review state beats the body text", () => {
  assert.equal(verdictFromReview(review({ state: "APPROVED", body: "anything" })), "PASS");
  assert.equal(verdictFromReview(review({ state: "CHANGES_REQUESTED", body: "anything" })), "MODIFY");
  assert.equal(verdictFromReview(review({ state: "COMMENTED", body: "cursor: PASS at x" })), "PASS");
});

test("a review verdict is pinned to its commit_id", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [review({ state: "APPROVED", commitId: HEAD })],
    comments: [],
  });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "ditto");
  assert.equal(pinned[0]?.headSha, HEAD);
  assert.equal(pinned[0]?.verdict, "PASS");
});

test("a review with no commit_id is dropped rather than assumed current", () => {
  const pinned = collectPinnedVerdicts({ reviews: [review({ commitId: null })], comments: [] });
  assert.deepEqual(pinned, []);
});

test("a comment verdict is pinned to the SHA it names", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      comment({
        body: `Replit: **MODIFY** at full head ${HEAD}`,
      }),
    ],
  });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "replit");
  assert.equal(pinned[0]?.headSha, HEAD);
  assert.equal(pinned[0]?.verdict, "MODIFY");
});

test("an unpinned comment verdict is dropped, so a stale PASS cannot release the gate", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [comment({ body: "@cursor says PASS on this change" })],
  });
  assert.deepEqual(pinned, []);
});

test("a Ditto-App comment is attributed to ditto even when posted under Joshua's login", () => {
  // Measured shape: `performed_via_github_app.slug = "ditto-code"` with
  // `user.login = "cryptoreporthub"`. Author login alone would misread this as
  // Joshua, or as a Replit report.
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      comment({
        body: "MC: **PASS** at `" + HEAD + "`",
        user: { login: "cryptoreporthub", type: "User" },
        performedViaGithubApp: { slug: "ditto-code" },
      }),
    ],
  });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "ditto");
});

test("the newest verdict sorts last so latest-wins reads correctly", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [review({ id: 10, state: "CHANGES_REQUESTED" }), review({ id: 20, state: "APPROVED" })],
    comments: [],
  });
  assert.deepEqual(
    pinned.map((p) => p.verdict),
    ["MODIFY", "PASS"],
  );
});
