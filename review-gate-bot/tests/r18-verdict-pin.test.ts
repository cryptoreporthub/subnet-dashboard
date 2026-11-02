import assert from "node:assert/strict";
import test from "node:test";
import { computeGate, verdictAt } from "../bot/lib/gate.js";
import { gateStateFrom } from "../bot/lib/gh.js";
import { hydrateVerdictPinsFromKv, MemoryVerdictPinStore } from "../bot/lib/verdict_pin.js";
import postVerdict from "../bot/tools/post_verdict.js";
import { collectPinnedVerdicts, CURSOR_BOT_LOGIN, VERDICT_PIN_TEST_REF, type CommentLike } from "../bot/lib/verdicts.js";

const H1 = "a".repeat(40);
const H2 = "b".repeat(40);
const REF = VERDICT_PIN_TEST_REF;

function cursorComment(id: number, body: string, createdAt: string, updatedAt?: string): CommentLike {
  return {
    id,
    body,
    createdAt,
    updatedAt,
    user: { login: CURSOR_BOT_LOGIN, type: "Bot" },
    performedViaGithubApp: null,
  };
}

function gateAt(head: string, comments: CommentLike[], store = new MemoryVerdictPinStore()) {
  return gateStateFrom({
    headSha: head,
    comments,
    reviews: [],
    suite: "clean",
    ref: REF,
    pinStore: store,
  });
}

test("row 1: Cursor PASS @ H1 edited to PASS @ H2 does not merge on H2", () => {
  const store = new MemoryVerdictPinStore();
  const first = cursorComment(1, `PASS at \`${H1}\``, "2026-10-26T04:00:00Z", "2026-10-26T04:00:00Z");
  collectPinnedVerdicts({ reviews: [], comments: [first], ref: REF, pinStore: store, resolveSha: () => H1 });
  const edited = cursorComment(1, `PASS at \`${H2}\``, "2026-10-26T04:00:00Z", "2026-10-26T06:00:00Z");
  const gate = gateAt(H2, [edited], store);
  assert.notEqual(gate.cursor, "PASS");
  assert.notEqual(gate.next, "mergeable");
});

test("row 2: Ditto FAIL edited to PASS stays blocked", () => {
  const store = new MemoryVerdictPinStore();
  const fail = {
    id: 2,
    body: `FAIL at \`${H1}\``,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T04:00:00Z",
    user: { login: "cryptoreporthub", type: "User" as const },
    performedViaGithubApp: { slug: "ditto-code", id: 3889634 },
  } satisfies CommentLike;
  collectPinnedVerdicts({ reviews: [], comments: [fail], ref: REF, pinStore: store, resolveSha: () => H1 });
  const edited = { ...fail, body: `PASS at \`${H1}\``, updatedAt: "2026-10-26T05:00:00Z" };
  const gate = gateAt(H1, [edited], store);
  assert.equal(gate.ditto, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("row 3: MC firstSeen FAIL survives edit to junk", () => {
  const store = new MemoryVerdictPinStore();
  const fail = {
    id: 3,
    body: `FAIL at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T04:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  collectPinnedVerdicts({ reviews: [], comments: [fail], ref: REF, pinStore: store });
  const junk = { ...fail, body: "Thanks, updated.", updatedAt: "2026-10-26T05:00:00Z" };
  const gate = gateAt(H1, [junk], store);
  assert.equal(gate.mc, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("row 4: edited MODIFY→PASS ignored; newer MODIFY comment wins", () => {
  const store = new MemoryVerdictPinStore();
  const modify = {
    id: 4,
    body: `MODIFY at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T04:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  const passNew = {
    id: 5,
    body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T05:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  collectPinnedVerdicts({ reviews: [], comments: [modify, passNew], ref: REF, pinStore: store });
  const edited = { ...modify, body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`, updatedAt: "2026-10-26T06:00:00Z" };
  const pinned = collectPinnedVerdicts({ reviews: [], comments: [edited, passNew], ref: REF, pinStore: store }).filter((p) => p.reviewer === "mc");
  assert.equal(verdictAt(pinned, "mc", H1), "PASS");
});

test("row 5: same-second body hash change without timestamp bump fails closed on PASS upgrade", () => {
  const store = new MemoryVerdictPinStore();
  const fail = cursorComment(10, `FAIL at \`${H1}\``, "2026-10-26T04:00:00.000Z", "2026-10-26T04:00:00.000Z");
  collectPinnedVerdicts({ reviews: [], comments: [fail], ref: REF, pinStore: store, resolveSha: () => H1 });
  const passSameSecond = cursorComment(10, `PASS at \`${H1}\``, "2026-10-26T04:00:00.000Z", "2026-10-26T04:00:00.000Z");
  const pinned = collectPinnedVerdicts({ reviews: [], comments: [passSameSecond], ref: REF, pinStore: store, resolveSha: () => H1 });
  assert.equal(pinned.at(-1)?.verdict, "FAIL");
});

test("row 6: first sight already edited never records PASS", () => {
  const editedPass = {
    id: 11,
    body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T05:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  const pinned = collectPinnedVerdicts({ reviews: [], comments: [editedPass], ref: REF, pinStore: new MemoryVerdictPinStore() });
  assert.deepEqual(pinned.filter((p) => p.reviewer === "mc"), []);
});

test("row 3b: firstSeen PASS @ H1 kept when body edited to junk", () => {
  const store = new MemoryVerdictPinStore();
  const pass = {
    id: 12,
    body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T04:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  collectPinnedVerdicts({ reviews: [], comments: [pass], ref: REF, pinStore: store });
  const junk = { ...pass, body: "noise", updatedAt: "2026-10-26T05:00:00Z" };
  const gate = gateAt(H1, [junk], store);
  assert.equal(gate.mc, "PASS");
});

test("T2: PASS without blocking field is allowed again (r10 schema)", async () => {
  const execute = postVerdict.execute as unknown as (input: unknown, ctx: unknown) => Promise<unknown>;
  const result = await execute(
    {
      headSha: H1,
      verdict: "PASS",
      body: "ok",
      skills: [{ skill: "adversarial-review", used: true, note: "ran" }],
    },
    {
      session: { purpose: "eval", continuationKey: undefined },
      host: { github: { getOctokit: async () => { throw new Error("no"); } } },
    },
  );
  assert.deepEqual(result, { posted: false, reason: "eval", verdict: "PASS" });
});

test("kv read failure is fail-closed for PASS", () => {
  class FailStore extends MemoryVerdictPinStore {
    override get(): undefined {
      throw new Error("kv down");
    }
  }
  const comment = cursorComment(20, `PASS at \`${H1}\``, "2026-10-26T04:00:00Z", "2026-10-26T04:00:00Z");
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [comment],
    ref: REF,
    pinStore: new FailStore(),
    resolveSha: () => H1,
  });
  assert.deepEqual(pinned, []);
});

test("MC fix A: PASS @ H1 then edit FAIL @ H1 then edit PASS @ H1 stays blocked", () => {
  const store = new MemoryVerdictPinStore();
  const pass = {
    id: 30,
    body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`,
    createdAt: "2026-10-26T04:00:00Z",
    updatedAt: "2026-10-26T04:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" as const },
    performedViaGithubApp: { id: 5501340, slug: "simibot" },
  } satisfies CommentLike;
  collectPinnedVerdicts({ reviews: [], comments: [pass], ref: REF, pinStore: store });
  const fail = {
    ...pass,
    body: `FAIL at ${H1}\n<!-- mc-verdict:${H1} -->`,
    updatedAt: "2026-10-26T05:00:00Z",
  };
  collectPinnedVerdicts({ reviews: [], comments: [fail], ref: REF, pinStore: store });
  const passAgain = {
    ...fail,
    body: `PASS at ${H1}\n<!-- mc-verdict:${H1} -->`,
    updatedAt: "2026-10-26T06:00:00Z",
  };
  const gate = gateAt(H1, [passAgain], store);
  assert.equal(gate.mc, "FAIL");
  assert.equal(gate.next, "blocked");
});

test("MC fix B: hydrate kv.get failure is fail-closed for PASS", async () => {
  const store = new MemoryVerdictPinStore();
  const comment = cursorComment(21, `PASS at \`${H1}\``, "2026-10-26T04:00:00Z", "2026-10-26T04:00:00Z");
  await hydrateVerdictPinsFromKv({
    kv: {
      get: async () => {
        throw new Error("kv down");
      },
      put: async () => {},
      delete: async () => {},
    },
    ref: REF,
    comments: [comment],
    store,
  });
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [comment],
    ref: REF,
    pinStore: store,
    resolveSha: () => H1,
  });
  assert.deepEqual(pinned, []);
});
