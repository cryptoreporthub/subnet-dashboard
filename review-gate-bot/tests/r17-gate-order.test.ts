import assert from "node:assert/strict";
import test from "node:test";
import { computeGate, verdictAt, type PinnedVerdict } from "../bot/lib/gate.js";
import { asComment, gateStateFrom } from "../bot/lib/gh.js";
import { collectPinnedVerdicts, GATE_BOT_LOGIN, SIMIBOT_APP_ID, VERDICT_PIN_TEST_REF, type CommentLike } from "../bot/lib/verdicts.js";
import { composeVerdictBody } from "../bot/tools/post_verdict.js";
import { marker } from "../bot/lib/tag.js";

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const SIMIBOT = { login: "simibot[bot]", type: "Bot" as const };
const SIMIBOT_APP = { id: SIMIBOT_APP_ID, slug: "simibot" };

function mcBotComment(
  id: number,
  verdict: "PASS" | "MODIFY" | "FAIL",
  createdAt: string,
  updatedAt?: string,
): CommentLike {
  const body = `${marker("mc-verdict", HEAD)}\n${composeVerdictBody({
    verdict,
    headSha: HEAD,
    body: "Review notes.",
    skills: [{ skill: "adversarial-review", used: true, note: "ran" }],
  })}`;
  return {
    id,
    body,
    createdAt,
    updatedAt,
    user: { login: `${GATE_BOT_LOGIN}`, type: "Bot" },
    performedViaGithubApp: { slug: "simi-revision" },
  };
}

function simibotMcComment(
  id: number,
  verdict: "PASS" | "MODIFY" | "FAIL",
  createdAt: string,
  updatedAt?: string,
): CommentLike {
  const body = `${verdict} at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  return {
    id,
    body,
    createdAt,
    updatedAt,
    user: SIMIBOT,
    performedViaGithubApp: SIMIBOT_APP,
  };
}

function gateWithMcComments(comments: CommentLike[]) {
  return gateStateFrom({
    headSha: HEAD,
    comments,
    reviews: [],
    suite: "clean",
    replitTaggedForSha: HEAD,
    replitTaggedAt: "2026-10-26T04:00:00Z",
  });
}

test("ordering uses createdAt only: edited PASS after later FAIL still leaves FAIL at the slot", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      {
        id: 1,
        body: `PASS at \`${HEAD}\``,
        createdAt: "2026-10-26T04:00:00Z",
        updatedAt: "2026-10-26T04:10:00Z",
        user: { login: "cursor[bot]", type: "Bot" },
        performedViaGithubApp: null,
      },
      {
        id: 2,
        body: `FAIL at \`${HEAD}\``,
        createdAt: "2026-10-26T04:05:00Z",
        user: { login: "cursor[bot]", type: "Bot" },
        performedViaGithubApp: null,
      },
    ],
    resolveSha: () => HEAD,
  });
  assert.deepEqual(
    pinned.map((p) => p.verdict),
    ["PASS", "FAIL"],
  );
  assert.equal(verdictAt(pinned, "cursor", HEAD), "FAIL");
});

test("two verdicts at the same createdAt disagreeing fail closed to FAIL", () => {
  const t = "2026-10-26T04:00:00.000Z";
  const pinned: PinnedVerdict[] = [
    { reviewer: "mc", verdict: "PASS", headSha: HEAD, at: t },
    { reviewer: "mc", verdict: "FAIL", headSha: HEAD, at: t },
  ];
  assert.equal(verdictAt(pinned, "mc", HEAD), "FAIL");
});

test("MC edited comment cannot supply PASS (gate bot marker form)", () => {
  const passThenEdited = mcBotComment(1, "PASS", "2026-10-26T04:00:00Z", "2026-10-26T06:00:00Z");
  const failNewer = mcBotComment(2, "FAIL", "2026-10-26T04:05:00Z");
  const gate = gateWithMcComments([passThenEdited, failNewer]);
  assert.equal(gate.mc, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("MC FAIL edited to PASS in place does not pin MC PASS", () => {
  const failEditedToPass = simibotMcComment(1, "FAIL", "2026-10-26T04:00:00Z", "2026-10-26T06:00:00Z");
  failEditedToPass.body = `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`;
  const pinned = collectPinnedVerdicts({ reviews: [], comments: [failEditedToPass], ref: VERDICT_PIN_TEST_REF }).filter((p) => p.reviewer === "mc");
  assert.deepEqual(pinned, []);
});

test("later new MC PASS replaces an earlier FAIL on the same head (no sticky FAIL)", () => {
  const fail = simibotMcComment(1, "FAIL", "2026-10-26T04:00:00Z");
  const pass = simibotMcComment(2, "PASS", "2026-10-26T05:00:00Z");
  const pinned = collectPinnedVerdicts({ reviews: [], comments: [fail, pass] }).filter((p) => p.reviewer === "mc");
  assert.equal(pinned.at(-1)?.verdict, "PASS");
  assert.equal(verdictAt(pinned, "mc", HEAD), "PASS");
});

test("owner Replit PASS still pins when the report comment was edited", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      {
        id: 10,
        body: `Replit: PASS at ${HEAD}`,
        createdAt: "2026-10-26T04:00:00Z",
        updatedAt: "2026-10-26T05:00:00Z",
        user: { login: "cryptoreporthub", type: "User" },
        performedViaGithubApp: null,
      },
    ],
    resolveSha: () => HEAD,
  });
  assert.equal(pinned[0]?.reviewer, "replit");
  assert.equal(pinned[0]?.verdict, "PASS");
});

test("gate replay case A (G2): edited MC PASS after FAIL must stay blocked", () => {
  const raw = [
    {
      id: 1,
      body: `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`,
      created_at: "2026-10-26T04:00:00Z",
      updated_at: "2026-10-26T06:00:00Z",
      user: SIMIBOT,
      performed_via_github_app: SIMIBOT_APP,
    },
    {
      id: 2,
      body: `FAIL at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`,
      created_at: "2026-10-26T04:05:00Z",
      user: SIMIBOT,
      performed_via_github_app: SIMIBOT_APP,
    },
  ];
  const gate = gateStateFrom({
    headSha: HEAD,
    comments: raw.map((c) => asComment(c)),
    reviews: [],
    suite: "clean",
  });
  assert.equal(gate.mc, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("gate replay case B (G4): edited PASS then newer FAIL stays blocked", () => {
  const raw = [
    {
      id: 1,
      body: `PASS at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`,
      created_at: "2026-10-26T04:00:00Z",
      updated_at: "2026-10-26T04:02:00Z",
      user: SIMIBOT,
      performed_via_github_app: SIMIBOT_APP,
    },
    {
      id: 2,
      body: `FAIL at ${HEAD}\n<!-- mc-verdict:${HEAD} -->`,
      created_at: "2026-10-26T04:05:00Z",
      user: SIMIBOT,
      performed_via_github_app: SIMIBOT_APP,
    },
  ];
  const gate = gateStateFrom({
    headSha: HEAD,
    comments: raw.map((c) => asComment(c)),
    reviews: [],
    suite: "clean",
  });
  assert.equal(gate.mc, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("a newer MC PASS comment replaces an older FAIL on the same head in computeGate", () => {
  const state = computeGate({
    headSha: HEAD,
    suite: "clean",
    verdicts: [
      { reviewer: "mc", verdict: "FAIL", headSha: HEAD, at: "2026-10-26T04:00:00Z" },
      { reviewer: "mc", verdict: "PASS", headSha: HEAD, at: "2026-10-26T05:00:00Z" },
      { reviewer: "cursor", verdict: "PASS", headSha: HEAD, at: "2026-10-26T04:10:00Z" },
      { reviewer: "ditto", verdict: "PASS", headSha: HEAD, at: "2026-10-26T04:11:00Z" },
    ],
    replitTaggedForSha: HEAD,
    replitTaggedAt: "2026-10-26T04:00:00Z",
  });
  assert.equal(state.mc, "PASS");
  assert.notEqual(state.next, "blocked");
});
