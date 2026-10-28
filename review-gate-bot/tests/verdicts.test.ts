import assert from "node:assert/strict";
import test from "node:test";
import {
  collectPinnedVerdicts,
  firstLine,
  GATE_BOT_LOGIN,
  hasOwnMarker,
  isDittoComment,
  isDittoReview,
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
});

test("a Ditto-App comment posted under Joshua's account is Ditto, not Joshua", () => {
  const c = comment({ user: { login: "cryptoreporthub", type: "User" }, performedViaGithubApp: { slug: "ditto-code" } });
  assert.equal(isDittoComment(c), true);
});

test("a plain owner-account comment is not Ditto", () => {
  const c = comment();
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
  assert.equal(verdictFromReview(review({ state: "COMMENTED", body: "cursor: PASS at " + HEAD })), "PASS");
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
  assert.notEqual(parseVerdictToken("**PASS** — clean."), "PASS", "a note after PASS takes it back");
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
  // A sentence that merely contains the word opens no verdict at all, and
  // "no verdict" can never release the gate.
  assert.equal(parseVerdictToken("The suite has tests FAIL on two cases, so overall not PASS."), undefined);
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
    user: { login: "simi-revision[bot]", type: "Bot" },
    performedViaGithubApp: { slug: "simi-revision" },
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
    user: { login: "simi-revision", type: "User" },
    performedViaGithubApp: null,
  };
  assert.equal(isOwnComment(squatter), false);
});

test("two markers in one body are not trusted", () => {
  const doubled: CommentLike = {
    id: 6,
    body: `${marker("mc-verdict", HEAD)}\n${marker("mc-verdict", OTHER)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "simi-revision[bot]", type: "Bot" },
    performedViaGithubApp: { slug: "simi-revision" },
  };
  assert.equal(hasOwnMarker(doubled, "mc-verdict", HEAD), false);
});

test("parseMarkers reads slot and SHA and ignores anything else", () => {
  const parsed = parseMarkers(
    [marker("replit", HEAD), "<!-- subnet-review-gate:bogus:" + HEAD + " -->", "<!-- unrelated -->"].join("\n"),
  );
  assert.deepEqual(parsed, [{ slot: "replit", headSha: HEAD }]);
});

test("the gate's own login is the App's bot login, a name no person can hold", () => {
  assert.equal(GATE_BOT_LOGIN, "simi-revision[bot]");
});

test("a marker from the owner's own account is not the gate's, because MC and Claude post there too", () => {
  const fromOwner: CommentLike = {
    id: 7,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    createdAt: "2026-10-26T04:00:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performedViaGithubApp: null,
  };
  assert.equal(isOwnComment(fromOwner), false);
  assert.equal(hasOwnMarker(fromOwner, "mc-verdict", HEAD), false);
  assert.deepEqual(collectPinnedVerdicts({ reviews: [], comments: [fromOwner] }), [], "no MC verdict is read from it");
});

// --- simibot: the Grokbot App posts MC verdicts, trusted by App ID ---------

const SIMIBOT = { login: "simibot[bot]", type: "Bot" };
const SIMIBOT_APP = { id: 5501340, slug: "simibot" };

function mcVerdictFrom(overrides: Partial<CommentLike>): CommentLike {
  return comment({ body: `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``, ...overrides });
}

function pinned(comments: CommentLike[], reviews: ReviewLike[] = []): string[][] {
  return collectPinnedVerdicts({ reviews, comments }).map((p) => [p.reviewer, p.verdict, p.headSha]);
}

test("simibot's MC verdict, posted by the simibot App (id 5501340), is the MC verdict", () => {
  assert.deepEqual(pinned([mcVerdictFrom({ user: SIMIBOT, performedViaGithubApp: SIMIBOT_APP })]), [["mc", "PASS", HEAD]]);
});

test("a comment named simibot but attributed to a different App is refused", () => {
  const squatter = mcVerdictFrom({ user: SIMIBOT, performedViaGithubApp: { id: 1236702, slug: "simibot" } });
  assert.deepEqual(pinned([squatter]), []);
});

test("a simibot comment with no App attribution is refused: the login alone is only a name", () => {
  assert.deepEqual(pinned([mcVerdictFrom({ user: SIMIBOT, performedViaGithubApp: null })]), []);
});

test("the owner's account carrying simibot's App id is still not simibot's verdict", () => {
  const ownerViaApp = mcVerdictFrom({ user: { login: "cryptoreporthub", type: "User" }, performedViaGithubApp: SIMIBOT_APP });
  assert.deepEqual(pinned([ownerViaApp]), []);
});

test("simibot cannot fill the cursor-ditto or replit slots, only the MC slot", () => {
  const cursorDitto = comment({
    body: `${marker("cursor-ditto", HEAD)}\nCursor: **PASS**`,
    user: SIMIBOT,
    performedViaGithubApp: SIMIBOT_APP,
  });
  const replit = comment({
    body: `${marker("replit", HEAD)}\nReplit: **PASS**`,
    user: SIMIBOT,
    performedViaGithubApp: SIMIBOT_APP,
  });
  assert.deepEqual(pinned([cursorDitto, replit]), []);
});

test("a simibot comment carrying two MC markers is refused, as the gate's own bot's is", () => {
  const doubled = mcVerdictFrom({
    body: `${marker("mc-verdict", HEAD)}\n${marker("mc-verdict", OTHER)}\nMC: **PASS**`,
    user: SIMIBOT,
    performedViaGithubApp: SIMIBOT_APP,
  });
  assert.deepEqual(pinned([doubled]), []);
});

test("a review from simibot is never an MC verdict", () => {
  assert.deepEqual(pinned([], [review({ user: SIMIBOT, body: "MC: **PASS**" })]), []);
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

test("an abbreviated SHA needs 12 hex characters: 7 is 28 bits, which a PR author can grind", () => {
  assert.equal(shaClaimedByComment(comment({ body: "head deadbeefcafe" })), "deadbeefcafe");
  assert.equal(shaClaimedByComment(comment({ body: "head deadbeefcaf" })), undefined);
  assert.equal(shaClaimedByComment(comment({ body: "head deadbee" })), undefined);
  assert.equal(shaClaimedByComment(comment({ body: "on `deadbee` only" })), undefined);
});

test("a delimited short SHA is a claim without a keyword", () => {
  assert.equal(shaClaimedByComment(comment({ body: "on `deadbeefcafe` only" })), "deadbeefcafe");
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
    comments: [comment({ body: "Replit: PASS head deadbeefcafe" })],
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
  assert.notEqual(parseVerdictToken("PASS — no blocking findings"), "PASS");
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
  assert.equal(pinnedFor(`PASS \`${HEAD}\``), HEAD);
  // A bare SHA after PASS parses as PASS, but the claim rule takes a bare 40-character run
  // as prose, so it pins to nothing and cannot count for a head.
  assert.equal(pinnedFor(`PASS ${HEAD}`), undefined);
  assert.equal(pinnedFor(`PASS. See commit ${HEAD}`), undefined, "a note between PASS and the SHA is no PASS");
});

test("two different heads named in one verdict pin to neither", () => {
  assert.equal(pinnedFor(`Superseded by \`${HEAD}\`. PASS on commit ${OTHER}`), undefined);
  assert.equal(pinnedFor(`PASS head ${OTHER}, current head is \`${HEAD}\``), undefined);
});

test("a short and a full form of one head after a PASS name two SHAs, so no single head is pinned", () => {
  assert.equal(pinnedFor(`PASS head ${HEAD.slice(0, 12)} (\`${HEAD}\`)`), undefined);
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
    performedViaGithubApp: { slug: "simi-revision" },
  };
  assert.equal(hasOwnMarker(forged, "mc-verdict", HEAD), false);
});

test("verdict lines in the shapes reviewers decorate them with still read", () => {
  assert.equal(parseVerdictToken("**Verdict: PASS**"), "PASS");
  assert.equal(parseVerdictToken("✅ PASS"), "PASS");
  assert.equal(parseVerdictToken("## ❌ FAIL — two blockers"), "FAIL");
  assert.equal(parseVerdictToken("🟡 **MODIFY** at `abc`"), "MODIFY");
  assert.equal(parseVerdictToken("~~PASS~~"), undefined);
  assert.equal(parseVerdictToken("> PASS"), undefined);
});

test("a caveat after a PASS takes it back under the allowlist", () => {
  assert.notEqual(parseVerdictToken("PASS — not blocking"), "PASS");
  assert.notEqual(parseVerdictToken("PASS — no regressions, but docs lag"), "PASS");
  assert.notEqual(parseVerdictToken("PASS, however see the note below"), "PASS");
  assert.equal(parseVerdictToken("PASS — not approved"), undefined);
  assert.equal(parseVerdictToken("PASS until the suite runs"), undefined);
});

test("a verdict comment edited after a later one is the last thing said, so it sorts last", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      comment({
        id: 1,
        body: `PASS at \`${HEAD}\``,
        createdAt: "2026-10-26T04:00:00Z",
        updatedAt: "2026-10-26T04:10:00Z",
        user: CURSOR,
      }),
      comment({
        id: 2,
        body: `FAIL at \`${HEAD}\``,
        createdAt: "2026-10-26T04:05:00Z",
        user: CURSOR,
      }),
    ],
  });
  assert.deepEqual(
    pinned.map((p) => p.verdict),
    ["FAIL", "PASS"],
  );
});

test("an unedited comment keeps its creation order", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      comment({ id: 1, body: `PASS at \`${HEAD}\``, createdAt: "2026-10-26T04:00:00Z", updatedAt: "2026-10-26T04:00:00Z", user: CURSOR }),
      comment({ id: 2, body: `FAIL at \`${HEAD}\``, createdAt: "2026-10-26T04:05:00Z", user: CURSOR }),
    ],
  });
  assert.deepEqual(
    pinned.map((p) => p.verdict),
    ["PASS", "FAIL"],
  );
});

// --- A PASS counts only when nothing but a head pointer follows it -----------------------
// Allowlist, fail closed: after PASS, an optional head SHA (`at <sha>`, `at head <sha>`,
// `head <sha>`, or a bare SHA, backticked or not), trailing punctuation, and a `-grokbot` or
// `-simibot` signature. Anything else takes the PASS back. The NOT_PASS rows are the phrasings
// MC and Cursor named at 44ce7ea, plus the caveats and header shapes that now stop counting.

const NOT_PASS = [
  // Phrasings MC named at 44ce7ea.
  "PASS — do not approve this PR",
  "PASS, do not merge",
  "PASS (do not approve)",
  "PASS — block this PR",
  "PASS — reject",
  "PASS — withdrawn",
  "PASS — stale",
  "PASS — unsafe",
  "PASS — do not ship",
  "PASS - do not merge",
  "PASS, not approving",
  "PASS — wait",
  "PASS — nope",
  "PASS, ignore this",
  "PASS — hold",
  "PASS — don\u2019t merge",
  "PASS — can\u2019t ship",
  "PASS — won\u2019t merge",
  // Caveats and notes that now stop counting, as the owner set the policy.
  "**PASS** — clean.",
  "PASS — no blocking findings",
  "PASS, but docs lag",
  "PASS, not blocking",
  "PASS (no blocking findings)",
  "PASS — no regressions, but docs lag",
  "PASS, however see the note below",
  "PASS until the suite runs",
  "PASS. See commit " + HEAD,
  "PASS head " + HEAD.slice(0, 12) + " (`" + HEAD + "`)",
  "PASS at x",
  // MC's header shape and Replit's natural wording: not PASS under exact-PASS, by policy.
  "PASS — MC adversarial review of #1522 at head `" + HEAD + "`",
  "Replit: PASS — reviewed draft #1522 at exact head " + HEAD + ".",
];

const CLEAN_PASS = [
  "PASS",
  "PASS.",
  "PASS!",
  "PASS at " + HEAD,
  "PASS at `" + HEAD + "`",
  "PASS at head " + HEAD,
  "PASS head " + HEAD,
  "PASS `" + HEAD + "`",
  "PASS `" + HEAD + "`",
  "PASS -grokbot",
  "PASS at `" + HEAD + "` -grokbot",
  "PASS at `" + HEAD + "`.",
  "MC: **PASS** at `" + HEAD + "`",
  "cursor: **PASS** at `" + HEAD + "`",
  "Replit: PASS head " + HEAD,
];

for (const line of NOT_PASS) {
  test(`a PASS with anything else after it is no PASS: "${line}"`, () => {
    assert.notEqual(parseVerdictToken(line), "PASS", `"${line}" must not read as PASS`);
  });
}

for (const line of CLEAN_PASS) {
  test(`a PASS with only a head pointer after it is a PASS: "${line}"`, () => {
    assert.equal(parseVerdictToken(line), "PASS");
  });
}

test("two SHAs after a PASS is no PASS, because the verdict cannot name one head", () => {
  assert.notEqual(parseVerdictToken(`PASS at ${HEAD} ${OTHER}`), "PASS");
});

test("MODIFY and FAIL first lines parse as before, whatever follows them", () => {
  assert.equal(parseVerdictToken("MODIFY — MC adversarial review of #1522 at head `" + HEAD + "`"), "MODIFY");
  assert.equal(parseVerdictToken("Replit: MODIFY — reviewed draft #1522 at exact head " + HEAD), "MODIFY");
  assert.equal(parseVerdictToken("FAIL — tests failing, do not merge"), "FAIL");
  assert.equal(parseVerdictToken("MODIFY, do not deploy until Joshua says GO"), "MODIFY");
});

test("MC's own PASS-with-a-withdrawal still reads as no verdict, not as PASS", () => {
  assert.equal(parseVerdictToken("PASS, do not deploy until Joshua says GO"), undefined);
});

// --- MC's formal verdict: SimiBot's App, the mc-verdict marker, and the newest wins -------

function simibotMc(body: string, overrides: Partial<CommentLike> = {}): CommentLike {
  return comment({ body, user: SIMIBOT, performedViaGithubApp: SIMIBOT_APP, ...overrides });
}

function mcEntries(comments: CommentLike[]): ReturnType<typeof collectPinnedVerdicts> {
  return collectPinnedVerdicts({ reviews: [], comments }).filter((p) => p.reviewer === "mc");
}

test("SimiBot's PASS in the mc-verdict form, from its App, pins MC at that head", () => {
  assert.deepEqual(pinned([simibotMc(`PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`)]), [["mc", "PASS", HEAD]]);
});

test("the mc-verdict form from a different App ID is refused", () => {
  const body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([simibotMc(body, { performedViaGithubApp: { id: 1236702, slug: "simibot" } })]), []);
});

test("the mc-verdict form from the right App ID under another login is refused", () => {
  const body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([simibotMc(body, { user: { login: "someone-else[bot]", type: "Bot" } })]), []);
});

test("the owner's account posting the mc-verdict form is not MC", () => {
  const body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([comment({ body, user: { login: "cryptoreporthub", type: "User" }, performedViaGithubApp: null })]), []);
});

test("the gate's own login posting the plain mc-verdict form is not MC", () => {
  const body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([comment({ body, user: { login: "simi-revision[bot]", type: "Bot" }, performedViaGithubApp: null })]), []);
});

test("an mc-verdict marker for another head pins to that head, which the gate ignores for this one", () => {
  assert.deepEqual(pinned([simibotMc(`PASS at ${OTHER}\n<!-- mc-verdict:${OTHER} -->`)]), [["mc", "PASS", OTHER]]);
});

test("two mc-verdict markers in one SimiBot body count for nothing", () => {
  const body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->\n<!-- mc-verdict:${OTHER} -->`;
  assert.deepEqual(pinned([simibotMc(body)]), []);
});

test("a SimiBot PASS the allowlist rejects is logged, not dropped silently", () => {
  const warnings: string[] = [];
  const original = console.warn;
  console.warn = (line: string) => {
    warnings.push(line);
  };
  try {
    assert.deepEqual(pinned([simibotMc(`PASS — do not merge\n<!-- mc-verdict:${HEAD} -->`)]), []);
  } finally {
    console.warn = original;
  }
  assert.ok(warnings.some((line) => JSON.parse(line).event === "verdict_line_unparsed"), "the rejected PASS is logged");
});

test("the newest SimiBot verdict at a head wins: an older PASS then a newer MODIFY is MODIFY", () => {
  const older = simibotMc(`PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, { id: 1, createdAt: "2026-10-26T04:00:00Z" });
  const newer = simibotMc(`MODIFY at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, { id: 2, createdAt: "2026-10-26T05:00:00Z" });
  assert.equal(mcEntries([older, newer]).at(-1)?.verdict, "MODIFY");
});

test("the newest SimiBot verdict at a head wins: an older MODIFY then a newer PASS is PASS", () => {
  const older = simibotMc(`MODIFY at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, { id: 1, createdAt: "2026-10-26T04:00:00Z" });
  const newer = simibotMc(`PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, { id: 2, createdAt: "2026-10-26T05:00:00Z" });
  assert.equal(mcEntries([older, newer]).at(-1)?.verdict, "PASS");
});

test("an older SimiBot verdict edited after a newer one is the last thing said, so it wins", () => {
  const older = simibotMc(`PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, {
    id: 1,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T06:00:00Z",
  });
  const newer = simibotMc(`MODIFY at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`, { id: 2, createdAt: "2026-10-26T05:00:00Z" });
  assert.equal(mcEntries([older, newer]).at(-1)?.verdict, "PASS");
});

// --- A SHA on the PASS line must name the head the verdict is pinned to ----------------------

const OLD_HEAD = "44ce7ea5dad700194036aea5b79958e0f176952d";

test("a SimiBot PASS that names an older head is no PASS for the head its marker names", () => {
  const body = `PASS at ${OLD_HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([simibotMc(body)]), []);
});

test("a SimiBot PASS whose SHA is a prefix of its marker's head still counts", () => {
  const body = `PASS at ${HEAD.slice(0, 12)}\n<!-- mc-verdict:${HEAD} -->`;
  assert.deepEqual(pinned([simibotMc(body)]), [["mc", "PASS", HEAD]]);
});

test("English words made of hex letters are not head pointers after a PASS", () => {
  for (const word of ["effaced", "defaced", "facade1", "deadbeef", "beefcafe"]) {
    assert.notEqual(parseVerdictToken(`PASS — ${word}`), "PASS", `"${word}" must not read as a head`);
  }
});

test("a PASS on a head pointer written with 'on' is no PASS: the allowed forms are at, head and bare", () => {
  assert.notEqual(parseVerdictToken(`PASS on \`${HEAD}\``), "PASS");
});
