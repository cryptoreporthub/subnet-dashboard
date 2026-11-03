import assert from "node:assert/strict";
import test from "node:test";
import {
  evalVerdictAlreadyAccepted,
  evalVerdictOnceKey,
  markEvalVerdictAccepted,
} from "../bot/lib/eval-verdict-once.js";
import postVerdict from "../bot/tools/post_verdict.js";

const execute = postVerdict.execute as unknown as (input: unknown, ctx: unknown) => Promise<Record<string, unknown>>;

const SESSION = "ses_eval_once";
const HEAD = "b".repeat(40);

const VERDICT = {
  headSha: HEAD,
  verdict: "MODIFY" as const,
  body: "A substantive review body for the eval harness.",
  skills: [
    { skill: "adversarial-review", used: true, note: "traced the real entry point from inlined method" },
    { skill: "owner-rules", used: true, note: "rule 1 complete snapshot requirement" },
    { skill: "settled-check", used: true, note: "not covered by a prior lock" },
  ],
};

import type { HostKvApi } from "@grok/agent-sdk/kv";

type Json = Awaited<ReturnType<HostKvApi["get"]>>;
type JsonIn = Parameters<HostKvApi["put"]>[1];

function kv() {
  const store = new Map<string, JsonIn>();
  return {
    store,
    async get(key: string): Promise<Json> {
      return store.get(key);
    },
    async put(key: string, value: JsonIn): Promise<void> {
      store.set(key, value);
    },
  };
}

function ctxEval(store: ReturnType<typeof kv>) {
  return {
    session: { id: SESSION, purpose: "eval" as const, continuationKey: undefined },
    host: { kv: store, github: { getOctokit: async () => { throw new Error("no github"); } } },
  };
}

test("eval harness: a second successful post_verdict in the same session is refused (already-posted-eval)", async () => {
  const store = kv();
  const ctx = ctxEval(store);
  const first = await execute(VERDICT, ctx);
  assert.deepEqual(first, { posted: true, reason: "eval", verdict: "MODIFY" });
  assert.equal(await evalVerdictAlreadyAccepted(store, SESSION), true);
  assert.equal(store.store.get(evalVerdictOnceKey(SESSION)), true);
  const second = await execute({ ...VERDICT, verdict: "PASS" }, ctx);
  assert.deepEqual(second, { posted: false, reason: "already-posted-eval", verdict: "PASS" });
});

test("eval harness: skill-not-read refusal does not consume the once slot", async () => {
  const store = kv();
  const bad = await execute(
    {
      ...VERDICT,
      skills: [{ skill: "outside-commenter", used: true, note: "claimed without opening" }],
    },
    ctxEval(store),
  );
  assert.equal(bad.reason, "skill-not-read");
  assert.equal(await evalVerdictAlreadyAccepted(store, SESSION), false);
  await markEvalVerdictAccepted(store, SESSION);
  assert.equal(await evalVerdictAlreadyAccepted(store, SESSION), true);
});
