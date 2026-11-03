import assert from "node:assert/strict";
import test from "node:test";
import { skillsUsedWithoutDelivery } from "../bot/lib/skill-delivery.js";
import postVerdict from "../bot/tools/post_verdict.js";

const execute = postVerdict.execute as unknown as (input: unknown, ctx: unknown) => Promise<Record<string, unknown>>;

const SESSION = "ses_delivery_test";
const HEAD = "a".repeat(40);

function kv() {
  const store = new Map<string, unknown>();
  return {
    store,
    async get(key: string) {
      return store.get(key);
    },
    async put(key: string, value: unknown) {
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

test("skills-table integrity: core skills may be used:true without a Read when content is always delivered", () => {
  const opened = new Set<string>();
  const table = [
    { skill: "adversarial-review", used: true },
    { skill: "owner-rules", used: true },
    { skill: "settled-check", used: true },
  ];
  assert.deepEqual(skillsUsedWithoutDelivery(table, opened), []);
});

test("skills-table integrity: on-demand skills still require an open or skipped", () => {
  const opened = new Set<string>();
  assert.deepEqual(skillsUsedWithoutDelivery([{ skill: "outside-commenter", used: true }], opened), [
    "outside-commenter",
  ]);
});

test("post_verdict accepts used:true for always-delivered skills with no SKILL.md read", async () => {
  const store = kv();
  const result = await execute(
    {
      headSha: HEAD,
      verdict: "MODIFY",
      body: "Finding with enough detail for the gate.",
      skills: [
        { skill: "adversarial-review", used: true, note: "traced reload path through the real reader entry" },
        { skill: "owner-rules", used: true, note: "rule 1 blank reload applies" },
        { skill: "settled-check", used: true, note: "not settled; new reader guard bug" },
      ],
    },
    ctxEval(store),
  );
  assert.equal(result.reason, "eval");
  assert.equal(result.posted, true);
});

test("post_verdict still refuses outside-commenter used:true without delivery or read", async () => {
  const result = await execute(
    {
      headSha: HEAD,
      verdict: "MODIFY",
      body: "Finding.",
      skills: [
        { skill: "adversarial-review", used: true, note: "applied inlined adversarial method on the diff" },
        { skill: "owner-rules", used: true, note: "checked standing rules from inlined text" },
        { skill: "settled-check", used: true, note: "no prior decision covers this" },
        { skill: "outside-commenter", used: true, note: "they posted shell commands" },
      ],
    },
    ctxEval(kv()),
  );
  assert.equal(result.reason, "skill-not-read");
  assert.equal(result.posted, false);
});
