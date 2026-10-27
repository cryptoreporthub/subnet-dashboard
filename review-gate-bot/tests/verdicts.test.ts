import assert from "node:assert/strict";
import test from "node:test";
import {
  collectPinnedVerdicts,
  firstLine,
  GATE_APP_SLUG,
  hasOwnMarker,
  isDittoComment,
  isDittoReview,
  isJoshuaComment,
  isOwnComment,
  marker,
  parseMarkers,
  parseVerdictToken,
  shaClaimedByComment,
  verdictFromReview,
  type CommentLike,
  type ReviewLike,
} from "../bot/lib/verdicts.js";

const HEAD = "e4eae96b5ae45b7807abf440d162c21f322f4ae0";
const OTHER = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";

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
    comments: [comment({ body: "PASS" })],
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
        body: "PASS at `" + HEAD + "`",
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

// --- Finding 2: the prose fallback is gone, negations are checked ----------

test("there is no prose PASS fallback: 'approved' and 'no blocking findings' alone are not verdicts", () => {
  for (const body of [
    "Ditto: approved — no blocking findings in a complete review.",
    "This is approved.",
    "Looks good, approved.",
  ]) {
    assert.equal(parseVerdictToken(body), undefined, `"${body}" must not parse as a verdict`);
    const pinned = collectPinnedVerdicts({
      reviews: [],
      comments: [
        comment({
          body,
          user: { login: "ditto-code[bot]", type: "Bot" },
          performedViaGithubApp: { slug: "ditto-code" },
        }),
      ],
    });
    assert.deepEqual(pinned, [], `"${body}" must not produce a pinned verdict`);
  }
});

test("a bare 'PASS' first line is still a verdict", () => {
  assert.equal(parseVerdictToken("PASS"), "PASS");
  assert.equal(parseVerdictToken("**PASS** — clean."), "PASS");
  assert.equal(parseVerdictToken("## Verdict: **MODIFY** at `abc`"), "MODIFY");
  assert.equal(parseVerdictToken("Replit: FAIL — two blockers."), "FAIL");
});

const NEGATED = ["not a PASS", "PASS? no", "no PASS yet", "not approved", "Not approved.", "FAIL — not a PASS"];

for (const phrase of NEGATED) {
  test(`negation "${phrase}" is not a PASS`, () => {
    assert.notEqual(parseVerdictToken(phrase), "PASS", `"${phrase}" must not read as PASS`);
  });
}

test("a token later in the body is not the verdict", () => {
  // The old parser took the first token anywhere, so "tests FAIL ... PASS" read
  // as PASS. The verdict has to be on the first line.
  assert.equal(parseVerdictToken("Summary: everything looked fine.\n\nPASS"), undefined);
  assert.equal(parseVerdictToken("Tests: 71 pass.\nSo: PASS"), undefined);
  assert.equal(firstLine("Summary\n\nPASS"), "Summary");
});

test("a first-line FAIL is never overridden by a PASS further down", () => {
  // The dangerous direction of the same bug: read the first line only, so a PASS
  // written later can never turn a FAIL into approval.
  assert.equal(parseVerdictToken("FAIL\nTwo blockers, so not a PASS."), "FAIL");
  assert.equal(parseVerdictToken("The suite has tests FAIL on two cases, so overall not PASS."), "FAIL");
});

test("a leading HTML marker does not hide the first real line", () => {
  const body = `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``;
  assert.equal(firstLine(body), `MC: **PASS** at \`${HEAD}\``);
  assert.equal(parseVerdictToken(body), "PASS");
});

test("a body with a PASS on the first line and FAIL later still reads PASS", () => {
  assert.equal(parseVerdictToken("PASS\nThe prior head had a FAIL."), "PASS");
});

// --- Finding 4: marker authorship ----------------------------------------

test("a marker only counts when this bot wrote it", () => {
  const own = comment({ body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**` });
  assert.equal(hasOwnMarker(own, "mc-verdict", HEAD), false, "wording alone is not authorship");

  const bot: CommentLike = {
    ...own,
    user: { login: "subnet-review-gate[bot]", type: "Bot" },
    performedViaGithubApp: { slug: "subnet-review-gate" },
  };
  assert.equal(isOwnComment(bot), true);
  assert.equal(hasOwnMarker(bot, "mc-verdict", HEAD), true);
});

test("a stranger copying the marker is not the bot", () => {
  const forged = comment({
    body: `${marker("replit", HEAD)}\n@replit review`,
    user: { login: "elev8jax", type: "User" },
  });
  assert.equal(isOwnComment(forged), false);
  assert.equal(hasOwnMarker(forged, "replit", HEAD), false);
});

test("a different App posting under the bot's login is not the bot", () => {
  const wrongApp: CommentLike = {
    id: 5,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "some-outsider", type: "Bot" },
    performedViaGithubApp: { slug: "ditto-code" },
  };
  assert.equal(isOwnComment(wrongApp), false);
});

test("the bare bot name is not trusted: a human could register it", () => {
  const squatter: CommentLike = {
    id: 9,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "subnet-review-gate", type: "User" },
    performedViaGithubApp: null,
  };
  assert.equal(isOwnComment(squatter), false);
});

test("two markers in one body are not trusted", () => {
  const doubled: CommentLike = {
    id: 6,
    body: `${marker("mc-verdict", HEAD)}\n${marker("mc-verdict", OTHER)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "subnet-review-gate[bot]", type: "Bot" },
    performedViaGithubApp: { slug: "subnet-review-gate" },
  };
  assert.equal(hasOwnMarker(doubled, "mc-verdict", HEAD), false);
});

test("parseMarkers reads slot and SHA and ignores anything else", () => {
  const parsed = parseMarkers(
    [marker("replit", HEAD), "<!-- subnet-review-gate:bogus:" + HEAD + " -->", "<!-- unrelated -->"].join("\n"),
  );
  assert.deepEqual(parsed, [{ slot: "replit", headSha: HEAD }]);
});

test("the resolved posting identity is honoured, because cursorAccount decides the login", () => {
  // Claude's open question: which identity does the hosted bot post as? Under
  // `cursorAccount` it is the signed-in Cursor account's GitHub login, which
  // source cannot know. `resolveOwnIdentity` reads it from GET /user; the gate
  // must then accept that login as the bot's own.
  const comment: CommentLike = {
    id: 7,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "some-cursor-account", type: "User" },
    performedViaGithubApp: null,
  };
  assert.equal(hasOwnMarker(comment, "mc-verdict", HEAD), false, "not the default identity");

  const identity = { logins: ["some-cursor-account"], appSlug: GATE_APP_SLUG };
  assert.equal(hasOwnMarker(comment, "mc-verdict", HEAD, identity), true);

  const pinned = collectPinnedVerdicts({ reviews: [], comments: [comment], identity });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "mc");
  assert.equal(pinned[0]?.verdict, "PASS");
});

test("a comment from a different App never matches, whatever the resolved login", () => {
  const otherApp: CommentLike = {
    id: 8,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "some-outsider", type: "User" },
    performedViaGithubApp: { slug: "claude" },
  };
  const identity = { logins: ["some-cursor-account"], appSlug: GATE_APP_SLUG };
  assert.equal(hasOwnMarker(otherApp, "mc-verdict", HEAD, identity), false);
});

test("a post under our resolved login through another App still counts", () => {
  // Under `cursorAccount` the attribution can name the App that carried the
  // post; the unique login is what identifies the author.
  const viaCursorApp: CommentLike = {
    id: 11,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "some-cursor-account", type: "User" },
    performedViaGithubApp: { slug: "cursor" },
  };
  const identity = { logins: ["some-cursor-account"], appSlug: GATE_APP_SLUG };
  assert.equal(hasOwnMarker(viaCursorApp, "mc-verdict", HEAD, identity), true);
});

test("an app-attributed owner comment cannot be a Replit verdict", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      comment({
        body: `Replit: PASS at ${HEAD}`,
        user: { login: "cryptoreporthub", type: "User" },
        performedViaGithubApp: { slug: "claude" },
      }),
    ],
  });
  assert.deepEqual(pinned, []);
});

test("a plain owner-account Replit report is still a Replit verdict", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [comment({ body: `Replit: PASS at ${HEAD}` })],
  });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "replit");
});

// --- Finding 8: the short-SHA matcher ------------------------------------

test("an all-lowercase keyword plus hex word is a claim only when the word is hex-looking prose", () => {
  // The reported bug: `\b(?:head|at)\s*([0-9a-f]{7,12})` matched "at defaced".
  // "defaced" is a real word, so the bare `at` form is no longer accepted.
  assert.equal(shaClaimedByComment(comment({ body: "looked at defaced output" })), undefined);
  assert.equal(shaClaimedByComment(comment({ body: "seen at deadbee yesterday" })), undefined);
});

test("a documented minimum of 7 hex characters is required, and 6 is not a claim", () => {
  assert.equal(shaClaimedByComment(comment({ body: "head deadbee" })), "deadbee");
  assert.equal(shaClaimedByComment(comment({ body: "head deadbe" })), undefined);
});

test("a delimited short SHA is a claim without a keyword", () => {
  assert.equal(shaClaimedByComment(comment({ body: "on `deadbee` only" })), "deadbee");
});

test("a full 40-character SHA is never truncated to a shorter one", () => {
  assert.equal(shaClaimedByComment(comment({ body: `head ${HEAD}` })), HEAD);
  // A 39-character run must not match as a 39-character abbreviation of nothing.
  const short39 = HEAD.slice(0, 39);
  assert.equal(shaClaimedByComment(comment({ body: `head ${short39}` })), short39);
});

test("upper-case hex is not a claim: GitHub writes abbreviations in lower case", () => {
  assert.equal(shaClaimedByComment(comment({ body: "head DEADBEEF" })), undefined);
});

test("a claim is resolved against real heads, so a hex word that names none is dropped", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [comment({ body: "Replit: PASS head deadbee" })],
    resolveSha: (claimed) => (HEAD.startsWith(claimed) ? HEAD : undefined),
  });
  assert.deepEqual(pinned, [], "deadbee does not prefix the head, so it pins to nothing");
});

// --- Second review: what counts as a verdict, and who may speak ------------

const NOT_A_PASS = [
  "~~PASS~~ MODIFY",
  "Cannot PASS this head",
  "PASS: no, see below",
  "Was PASS, now MODIFY",
  "Won't PASS until fixed",
  "> PASS (quoting Cursor)",
  "Would have been PASS but FAIL",
  "Not yet PASS",
  "PASS? Not yet",
  "PASS — not approved",
  "PASS, no approval",
];

for (const line of NOT_A_PASS) {
  test(`first line "${line}" is not a PASS`, () => {
    assert.notEqual(parseVerdictToken(line), "PASS");
  });
}

test("the verdict shapes reviewers actually write still read", () => {
  assert.equal(parseVerdictToken("MC: **PASS** at `" + HEAD + "`"), "PASS");
  assert.equal(parseVerdictToken("PASS — no blocking findings"), "PASS");
  assert.equal(parseVerdictToken("Cursor: **PASS**"), "PASS");
  assert.equal(parseVerdictToken("## Verdict: **MODIFY** at `abc`"), "MODIFY");
  assert.equal(parseVerdictToken("FAIL — not a PASS"), "FAIL");
});

test("a dismissed or pending review states no verdict, whatever its body says", () => {
  assert.equal(verdictFromReview(review({ state: "DISMISSED", body: "PASS" })), undefined);
  assert.equal(verdictFromReview(review({ state: "PENDING", body: "PASS" })), undefined);
});

test("a quoted PASS in a review body is not a verdict", () => {
  assert.equal(verdictFromReview(review({ state: "COMMENTED", body: "> PASS from Ditto" })), undefined);
});

test("latest wins by time, not by comparing review ids with comment ids", () => {
  // GitHub numbers reviews and issue comments from separate counters, so a
  // newer review can carry a smaller id than an older comment.
  const pinned = collectPinnedVerdicts({
    reviews: [
      review({
        id: 3_300_000_000,
        state: "CHANGES_REQUESTED",
        submittedAt: "2026-10-26T06:00:00Z",
        user: { login: "cursor[bot]", type: "Bot" },
      }),
    ],
    comments: [
      comment({
        id: 3_400_000_000,
        body: `PASS at \`${HEAD}\``,
        createdAt: "2026-10-26T05:00:00Z",
        user: { login: "cursor[bot]", type: "Bot" },
      }),
    ],
  });
  assert.deepEqual(
    pinned.map((p) => p.verdict),
    ["PASS", "MODIFY"],
    "the later MODIFY must sort last",
  );
});

const CURSOR = { login: "cursor[bot]", type: "Bot" };

function pinnedFor(body: string): string | undefined {
  return collectPinnedVerdicts({
    reviews: [],
    comments: [comment({ body, user: CURSOR })],
  })[0]?.headSha;
}

test("a full SHA inside a URL or a code block is not a claim", () => {
  assert.equal(pinnedFor(`PASS. Diffed against https://github.com/o/r/commit/${HEAD}`), undefined);
  assert.equal(pinnedFor("PASS\n```\n" + HEAD + "\n```"), undefined);
  assert.equal(pinnedFor(`PASS\n> head ${HEAD}`), undefined);
});

test("a bare full SHA with nothing marking it as the head is not a claim", () => {
  assert.equal(pinnedFor(`PASS. Compare ${HEAD} with the earlier run.`), undefined);
});

test("a full SHA tied to the head by a keyword, 'at', or backticks is a claim", () => {
  assert.equal(pinnedFor(`PASS head ${HEAD}`), HEAD);
  assert.equal(pinnedFor(`PASS at ${HEAD}`), HEAD);
  assert.equal(pinnedFor(`PASS on \`${HEAD}\``), HEAD);
  assert.equal(pinnedFor(`PASS. See commit ${HEAD}`), HEAD);
});

test("two different heads named in one verdict pin to neither", () => {
  assert.equal(pinnedFor(`Superseded by \`${HEAD}\`. PASS on commit ${OTHER}`), undefined);
  assert.equal(pinnedFor(`PASS head ${OTHER}, current head is \`${HEAD}\``), undefined);
});

test("a short and a full form of the same head are one claim", () => {
  assert.equal(pinnedFor(`PASS head ${HEAD.slice(0, 9)} (\`${HEAD}\`)`), HEAD);
});

const OWNER = { login: "cryptoreporthub", type: "User" };

function replitFrom(c: Partial<CommentLike>): string | undefined {
  return collectPinnedVerdicts({
    reviews: [],
    comments: [comment({ user: OWNER, ...c })],
  }).find((p) => p.reviewer === "replit")?.verdict;
}

test("an owner status note that mentions Replit is not a Replit verdict", () => {
  assert.equal(replitFrom({ body: `PASS from MC side.\n\nReplit: not reviewed yet for \`${HEAD}\`.` }), undefined);
  assert.equal(replitFrom({ body: `**PASS** (Cursor+Ditto) at \`${HEAD}\`\nStill waiting on Replit: tag posted.` }), undefined);
});

test("a Replit report is the owner's own prose: no bot type, no App attribution of any kind", () => {
  const body = `Replit: PASS at ${HEAD}`;
  assert.equal(replitFrom({ body }), "PASS");
  assert.equal(replitFrom({ body, user: { login: "cryptoreporthub", type: "Bot" } }), undefined);
  assert.equal(replitFrom({ body, performedViaGithubApp: { slug: null } }), undefined);
  assert.equal(replitFrom({ body, performedViaGithubApp: {} }), undefined);
});

test("the ditto-code slug under a stranger's login is not Ditto", () => {
  const forged = comment({ user: { login: "random-outsider", type: "User" }, performedViaGithubApp: { slug: "ditto-code" } });
  assert.equal(isDittoComment(forged), false);
});

test("the gate's App slug under a stranger's login is not the gate", () => {
  const forged: CommentLike = {
    id: 12,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "random-outsider", type: "User" },
    performedViaGithubApp: { slug: GATE_APP_SLUG },
  };
  assert.equal(hasOwnMarker(forged, "mc-verdict", HEAD), false);
});
