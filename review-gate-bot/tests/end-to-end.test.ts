import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { asComment, asReview, gateStateFrom, replitTaggedIn } from "../bot/lib/gh.js";
import { needsReviewTurn } from "../bot/lib/gate.js";
import { composeVerdictBody } from "../bot/tools/post_verdict.js";
import { marker } from "../bot/lib/tag.js";

/**
 * The hole this file closes.
 *
 * The old tests fed `gate.json` — an already-computed gate state — straight into
 * `computeGate`. Every parser between "a comment exists on GitHub" and "the gate
 * sees an MC verdict" was untested, which is exactly how the gate shipped never
 * reading MC's own verdict: 71 green tests, and the headline flow never left
 * `review`.
 *
 * Everything here starts from **raw GitHub JSON** (`performed_via_github_app`,
 * `commit_id`, `submitted_at`, …), runs it through the same normalizers the
 * live path uses, and asserts on `next`.
 */

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const BASE = "882980b817986fdcd2766fb18d46525b8e1955fd";
const BOT = "subnet-review-gate";

/** The exact body `post_verdict` posts, marker included. */
function mcVerdictCommentBody(verdict: "PASS" | "MODIFY" | "FAIL", sha = HEAD): string {
  const body = composeVerdictBody({
    verdict,
    headSha: sha,
    body: "Traced `grace_multiple` through the expiry predicate. No regression.",
    skills: [
      { skill: "adversarial-review", used: true, note: "pushed 1e308 through the real predicate" },
      { skill: "owner-rules", used: true, note: "rule 4: fail-closed cycle" },
      { skill: "settled-check", used: false, note: "skipped: no prior decision on this symbol" },
    ],
  });
  return `${marker("mc-verdict", sha)}\n${body}`;
}

type RawComment = {
  id: number;
  body: string;
  created_at: string;
  user: { login: string; type?: string } | null;
  performed_via_github_app?: { slug?: string | null } | null;
};

/** A raw issue comment from this bot, as GitHub renders an App-installation post. */
function ownComment(id: number, body: string): RawComment {
  return {
    id,
    body,
    created_at: "2026-10-26T04:00:00Z",
    user: { login: `${BOT}[bot]`, type: "Bot" },
    performed_via_github_app: { slug: BOT },
  };
}

function cursorReview(id: number, state: string, sha = HEAD): {
  id: number;
  body: string;
  state: string;
  submitted_at: string;
  commit_id: string;
  user: { login: string; type: string };
} {
  return {
    id,
    body: "Cursor review",
    state,
    submitted_at: "2026-10-26T04:10:00Z",
    commit_id: sha,
    user: { login: "cursor[bot]", type: "Bot" },
  };
}

/** A Ditto review: no app key at all, bot login only (measured on #1515). */
function dittoReview(id: number, state: string, sha = HEAD): {
  id: number;
  body: string;
  state: string;
  submitted_at: string;
  commit_id: string;
  user: { login: string; type: string };
} {
  return {
    id,
    body: "Ditto: approved — no blocking findings in a complete review.",
    state,
    submitted_at: "2026-10-26T04:15:00Z",
    commit_id: sha,
    user: { login: "ditto-code[bot]", type: "Bot" },
  };
}

/** A Replit report, pasted onto the PR by Joshua's own account. */
function replitReport(id: number, verdict: string, sha = HEAD): RawComment {
  return {
    id,
    body: `Replit: ${verdict} — reviewed draft at exact head ${sha}.`,
    created_at: "2026-10-26T04:30:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performed_via_github_app: null,
  };
}

/** Run raw payloads through the live normalizers, then the pure gate. */
function gateFromRaw(input: {
  comments: readonly RawComment[];
  reviews: readonly Parameters<typeof asReview>[0][];
  suite: "clean" | "regressed" | "carried" | "missing";
  headSha?: string;
}) {
  const headSha = input.headSha ?? HEAD;
  const comments = input.comments.map((c) => asComment(c));
  const reviews = input.reviews.map((r) => asReview(r));
  return gateStateFrom({
    headSha,
    comments,
    reviews,
    suite: input.suite,
    replitTaggedForSha: replitTaggedIn(comments, headSha),
  });
}

// --- Finding 1: MC's own verdict is read back, author and SHA checked ------

test("end to end: raw GitHub JSON with all three other passes reaches tag_replit", () => {
  // MC's PASS is posted by the bot, so it is read back from the marker comment.
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS"))],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "PASS", "MC's own posted verdict must be read back into the gate");
  assert.equal(gate.cursor, "PASS");
  assert.equal(gate.ditto, "PASS");
  assert.equal(gate.next, "tag_replit");
});

test("end to end: the same three passes without the MC comment stay at review", () => {
  // The control for the test above: nothing else in the payload can produce mc.
  const gate = gateFromRaw({
    comments: [],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "missing");
  assert.equal(gate.next, "review");
});

test("end to end: after the replit tag and Replit's report the gate is mergeable", () => {
  const gate = gateFromRaw({
    comments: [
      ownComment(100, mcVerdictCommentBody("PASS")),
      ownComment(101, `${marker("replit", HEAD)}\n@replit review\n\nHead under review: ${HEAD}`),
      replitReport(102, "PASS"),
    ],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.replitTagged, true);
  assert.equal(gate.replit, "PASS");
  assert.equal(gate.next, "mergeable");
});

test("an MC verdict whose marker names another head does not count at this head", () => {
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS", BASE))],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "missing");
  assert.equal(gate.next, "review");
});

test("a marker comment copied by someone else is not an MC verdict", () => {
  const impostor: RawComment = {
    id: 200,
    body: mcVerdictCommentBody("PASS"),
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "elev8jax", type: "User" },
    performed_via_github_app: null,
  };
  const gate = gateFromRaw({
    comments: [impostor],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "missing");
  assert.equal(gate.next, "review");
});

test("MC's own PASS is never also read as a Cursor PASS", () => {
  // The bug this replaces: when the bot posted as cursor[bot], its own PASS
  // filled the Cursor slot. The Cursor slot must come only from Cursor.
  const asCursor: RawComment = {
    id: 300,
    body: mcVerdictCommentBody("PASS"),
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "cursor[bot]", type: "Bot" },
    performed_via_github_app: null,
  };
  const gate = gateFromRaw({
    comments: [asCursor],
    reviews: [cursorReview(10, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.cursor, "PASS", "the real Cursor approval still counts");
  assert.equal(gate.mc, "missing", "a cursor[bot] marker comment is not an MC verdict");
  assert.equal(gate.next, "review");
});

test("an MC MODIFY verdict holds the gate at review without spending another turn", () => {
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("MODIFY"))],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "MODIFY");
  // `computeGate` returns `review` for any MC verdict that is not a PASS, and
  // the gate cannot advance to `tag_replit` on a MODIFY.
  assert.equal(gate.next, "review");
  assert.notEqual(gate.next, "tag_replit");
  // But a present verdict must not spend another model turn: `post_verdict` is
  // at-most-once, so a re-review of this head could post nothing while burning
  // a turn on every later comment event.
  assert.equal(needsReviewTurn(gate), false);
  assert.equal(needsReviewTurn(gateFromRaw({ comments: [], reviews: [], suite: "missing" })), true);
});

test("end to end: a cursor-account identity is read back once resolved", () => {
  // The realistic production shape. Under `cursorAccount` the bot's comments
  // arrive under the signed-in account's login, not `subnet-review-gate[bot]`.
  // `readGateState` resolves that from GET /user before parsing; this is the
  // same path with the resolved identity supplied.
  const comments = [
    asComment({
      id: 100,
      body: mcVerdictCommentBody("PASS"),
      created_at: "2026-10-26T04:00:00Z",
      user: { login: "joshua-cursor", type: "User" },
      performed_via_github_app: null,
    }),
  ];
  const reviews = [asReview(cursorReview(10, "APPROVED")), asReview(dittoReview(20, "APPROVED"))];
  const identity = { logins: ["joshua-cursor"], appSlug: "subnet-review-gate" };

  const blind = gateStateFrom({ headSha: HEAD, comments, reviews, suite: "clean" });
  assert.equal(blind.mc, "missing", "the default identity does not match, so mc is unseen");

  const resolved = gateStateFrom({ headSha: HEAD, comments, reviews, suite: "clean", identity });
  assert.equal(resolved.mc, "PASS");
  assert.equal(resolved.next, "tag_replit");
});

// --- Finding 4: an app-attributed owner comment cannot fill the Replit slot --

test("an app-attributed cryptoreporthub comment saying 'Replit: PASS' is not a Replit verdict", () => {
  const appOwned: RawComment = {
    id: 400,
    body: `Replit: PASS at ${HEAD}`,
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    // Measured shape: an App comment surfacing under the owner's own login.
    performed_via_github_app: { slug: "claude" },
  };
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS")), appOwned],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.replit, "missing", "an App-attributed comment is not a Replit review");
  assert.equal(gate.replitTagged, false);
  assert.equal(gate.next, "tag_replit", "the gate must still need the Replit round trip");
  assert.notEqual(gate.next, "mergeable");
});

test("a plain owner-account Replit: PASS still counts, so the rejection is about attribution", () => {
  const gate = gateFromRaw({
    comments: [
      ownComment(100, mcVerdictCommentBody("PASS")),
      ownComment(101, `${marker("replit", HEAD)}\n@replit review`),
      replitReport(102, "PASS"),
    ],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.replit, "PASS");
  assert.equal(gate.next, "mergeable");
});

// --- Finding 5: the kv-only stall is gone ---------------------------------

test("a replit tag already on the PR counts even with no kv record", () => {
  // The stall: the tag comment exists (posted by another turn or before a
  // redeploy), kv has no `replit-tag:<pr>`, and the gate sat on tag_replit
  // forever. GitHub is the system of record.
  const tagComment = ownComment(101, `${marker("replit", HEAD)}\n@replit review`);
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS")), tagComment],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.replitTagged, true);
  assert.equal(gate.next, "await_replit");
});

test("a replit marker posted by someone else does not count as the tag", () => {
  const forged: RawComment = {
    id: 500,
    body: `${marker("replit", HEAD)}\n@replit review`,
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "elev8jax", type: "User" },
    performed_via_github_app: null,
  };
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS")), forged],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.replitTagged, false);
  assert.equal(gate.next, "tag_replit");
});

// --- Finding 2: no prose fallback -----------------------------------------

const NEGATIONS = [
  "not a PASS",
  "PASS? no",
  "no PASS yet",
  "not approved",
  "Changes requested. This is not approved.",
  "2 blocking findings, not approved",
];

for (const prose of NEGATIONS) {
  test(`prose "${prose}" on a Replit report does not count as PASS`, () => {
    const gate = gateFromRaw({
      comments: [
        ownComment(100, mcVerdictCommentBody("PASS")),
        ownComment(101, `${marker("replit", HEAD)}\n@replit review`),
        {
          id: 600,
          body: `Replit: ${prose} at ${HEAD}`,
          created_at: "2026-10-26T05:00:00Z",
          user: { login: "cryptoreporthub", type: "User" },
          performed_via_github_app: null,
        },
      ],
      reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
      suite: "clean",
    });
    assert.notEqual(gate.replit, "PASS", `"${prose}" must not release the gate`);
    assert.equal(gate.next, "await_replit");
  });
}

test("a Ditto review whose body says 'not approved' is not a PASS", () => {
  const gate = gateFromRaw({
    comments: [ownComment(100, mcVerdictCommentBody("PASS"))],
    reviews: [
      cursorReview(10, "APPROVED"),
      { ...dittoReview(20, "COMMENTED"), body: "Ditto: not approved — 2 blocking findings." },
    ],
    suite: "clean",
  });
  assert.notEqual(gate.ditto, "PASS");
  assert.equal(gate.next, "await_cursor_ditto");
});

test("an MC verdict body that mentions PASS later cannot override its first-line MODIFY", () => {
  const body = composeVerdictBody({
    verdict: "MODIFY",
    headSha: HEAD,
    body: "Two blockers. This is not a PASS, and it is not approved.",
    skills: [{ skill: "adversarial-review", used: true, note: "found it" }],
  });
  const gate = gateFromRaw({
    comments: [ownComment(100, `${marker("mc-verdict", HEAD)}\n${body}`)],
    reviews: [cursorReview(10, "APPROVED"), dittoReview(20, "APPROVED")],
    suite: "clean",
  });
  assert.equal(gate.mc, "MODIFY");
});

// --- The committed fixture path still agrees with the gate -----------------

test("the eval fixtures and the raw-JSON path agree on the headline case", () => {
  // Same inputs, two routes: the fixture file (already-computed) and raw JSON
  // run through the normalizers and the pure gate.
  const fixture = JSON.parse(
    readFileSync(join("evals/fixtures/gate-order", "gate.json"), "utf8"),
  ) as { headSha: string; mc: string; cursor: string; ditto: string; suite: string; next: string };

  const raw = gateFromRaw({
    headSha: fixture.headSha,
    comments: [ownComment(100, mcVerdictCommentBody("PASS", fixture.headSha))],
    reviews: [cursorReview(10, "APPROVED", fixture.headSha)],
    suite: fixture.suite as "clean" | "missing",
  });

  assert.equal(raw.mc, fixture.mc, "MC is read back from its own marker comment");
  assert.equal(raw.cursor, fixture.cursor);
  assert.equal(raw.ditto, fixture.ditto, "no Ditto verdict in the payload");
  assert.equal(raw.next, fixture.next, "two of three passes: Replit is never tagged");
  assert.notEqual(raw.next, "tag_replit");
});
