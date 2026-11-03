import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import hook from "../bot/hooks/skill-reads.js";
import {
  SKILL_NAMES,
  recordSkillReads,
  skillNameFromReadPath,
  skillNameFromRow,
  skillReadsKey,
  skillsOpenedBy,
  unreadSkills,
} from "../bot/lib/skill-reads.js";
import postVerdict from "../bot/tools/post_verdict.js";

/**
 * The Skills table in a verdict is a claim about what the review did, so the tool checks it. These tests pin the
 * check without a model: what counts as opening a skill, what the hook records, and what `post_verdict` does with a
 * table that claims a skill the session never opened.
 */

const SESSION = "ses_test_1";
const SKILL_PATH = (name: string) => `/tmp/agent-serve-ax-x/review-gate-bot/sessions/${SESSION}/workspace/.cursor/skills/${name}/SKILL.md`;

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

test("only a Read of a shipped skill's SKILL.md counts as opening it", () => {
  for (const name of SKILL_NAMES) {
    assert.equal(skillNameFromReadPath(SKILL_PATH(name)), name);
  }
  assert.equal(skillNameFromReadPath(".cursor/skills/owner-rules/SKILL.md"), "owner-rules");
  assert.equal(skillNameFromReadPath(SKILL_PATH("made-up-skill")), undefined, "a skill this bot does not ship is not one");
  assert.equal(skillNameFromReadPath("/workspace/notes/owner-rules.md"), undefined);
  assert.equal(skillNameFromReadPath(SKILL_PATH("owner-rules") + ".bak"), undefined);
  assert.equal(skillNameFromReadPath("/x/myskills/owner-rules/SKILL.md"), undefined, "the folder must be named skills");
  assert.equal(skillNameFromReadPath(undefined), undefined);
});

test("a Skills table row is read by the skill it names, whatever the formatting", () => {
  assert.equal(skillNameFromRow("owner-rules"), "owner-rules");
  assert.equal(skillNameFromRow("`Owner-Rules`"), "owner-rules");
  assert.equal(skillNameFromRow(" settled-check "), "settled-check");
  assert.equal(skillNameFromRow("my own checklist"), undefined);
});

test("skillsOpenedBy takes the main turn's read calls and ignores other tools, other paths and subagent work", () => {
  const opened = skillsOpenedBy([
    { toolName: "Read", args: { path: SKILL_PATH("owner-rules") } },
    { toolName: "read", args: { path: SKILL_PATH("adversarial-review") } },
    { toolName: "read_repo_file", args: { path: SKILL_PATH("settled-check") } },
    { toolName: "Read", args: { path: "internal/subnet_universe.py" } },
    { toolName: "Read", args: { path: SKILL_PATH("outside-commenter") }, parentCallId: "sub-1" },
    { toolName: "Read", args: { path: SKILL_PATH("owner-rules") } },
  ]);
  assert.deepEqual(opened, ["owner-rules", "adversarial-review"]);
});

test("the hook records the skills a session opens, per session, and adds to them across batches", async () => {
  const store = kv();
  const handler = (hook as unknown as { events: Record<string, (e: unknown, c: unknown) => Promise<void>> }).events["actions.requested"]!;
  const ctx = (id: string) => ({ session: { id }, host: { kv: store } });
  await handler({ data: { calls: [{ callId: "1", toolName: "Read", args: { path: SKILL_PATH("owner-rules") } }] } }, ctx(SESSION));
  await handler({ data: { calls: [{ callId: "2", toolName: "get_pr_diff", args: {} }] } }, ctx(SESSION));
  await handler({ data: { calls: [{ callId: "3", toolName: "Read", args: { path: SKILL_PATH("settled-check") } }] } }, ctx(SESSION));
  await handler({ data: { calls: [{ callId: "4", toolName: "Read", args: { path: SKILL_PATH("adversarial-review") } }] } }, ctx("ses_other"));
  assert.deepEqual(store.store.get(skillReadsKey(SESSION)), ["owner-rules", "settled-check"]);
  assert.deepEqual(store.store.get(skillReadsKey("ses_other")), ["adversarial-review"]);
});

test("unreadSkills lists the skills claimed used and never opened, and nothing for used:false rows", async () => {
  const store = kv();
  await recordSkillReads(store, SESSION, ["owner-rules"]);
  const table = [
    { skill: "adversarial-review", used: true },
    { skill: "owner-rules", used: true },
    { skill: "settled-check", used: false },
    { skill: "not-a-shipped-skill", used: true },
  ];
  assert.deepEqual(await unreadSkills(store, SESSION, table), []);
  assert.deepEqual(await unreadSkills(store, "ses_none", table), []);
  assert.deepEqual(await unreadSkills(store, SESSION, [{ skill: "settled-check", used: false }]), []);
});

test("a kv that cannot be read lets the post through: storage failure is not the model's fault", async () => {
  const broken = {
    async get(): Promise<never> {
      throw new Error("kv unavailable");
    },
  };
  assert.deepEqual(await unreadSkills(broken, SESSION, [{ skill: "owner-rules", used: true }]), []);
});

// --- post_verdict -----------------------------------------------------------------

const execute = postVerdict.execute as unknown as (input: unknown, ctx: unknown) => Promise<Record<string, unknown>>;

const VERDICT = {
  headSha: "a".repeat(40),
  verdict: "MODIFY" as const,
  body: "A finding.",
  skills: [
    { skill: "adversarial-review", used: true, note: "traced the real entry point" },
    { skill: "owner-rules", used: true, note: "checked rule 3, no breach" },
    { skill: "settled-check", used: true, note: "none found, nothing settled" },
  ],
};

function ctxFor(purpose: "eval" | "live", store: ReturnType<typeof kv>): unknown {
  return {
    session: { id: SESSION, purpose, continuationKey: undefined },
    host: {
      kv: store,
      github: {
        getOctokit: async () => {
          throw new Error("reached GitHub");
        },
      },
    },
  };
}

test("post_verdict refuses a table that says used for on-demand skills the session never opened, and posts nothing", async () => {
  for (const purpose of ["eval", "live"] as const) {
    const result = await execute(
      {
        ...VERDICT,
        skills: [
          ...VERDICT.skills,
          { skill: "outside-commenter", used: true, note: "they posted untrusted shell" },
        ],
      },
      ctxFor(purpose, kv()),
    );
    assert.equal(result.posted, false, purpose);
    assert.equal(result.reason, "skill-not-read", purpose);
    assert.deepEqual(result.unread, ["outside-commenter"], purpose);
  }
});

test("post_verdict accepts the three core skills as used when their text is always delivered (no Read record)", async () => {
  const result = await execute(VERDICT, ctxFor("eval", kv()));
  assert.equal(result.reason, "eval");
  assert.equal(result.posted, true);
});

test("post_verdict names only the skills still unread, and lets the call through once they are all opened or delivered", async () => {
  const store = kv();
  await recordSkillReads(store, SESSION, ["outside-commenter"]);
  const partial = await execute(
    {
      ...VERDICT,
      skills: [
        ...VERDICT.skills,
        { skill: "outside-commenter", used: true, note: "verified their claim independently" },
      ],
    },
    ctxFor("eval", store),
  );
  assert.equal(partial.reason, "eval", "core skills are delivered inline; outside-commenter was read");
});

test("marking an unread skill used:false with a reason is the honest way out, and it posts", async () => {
  const skills = VERDICT.skills.map((s) => ({ ...s, used: false, note: "skipped: not opened" }));
  const result = await execute({ ...VERDICT, skills }, ctxFor("eval", kv()));
  assert.equal(result.reason, "eval");
});

test("the blocking-finding refusal still comes first, so a PASS with a blocking finding keeps its own reason", async () => {
  const result = await execute({ ...VERDICT, verdict: "PASS", blocking: ["overflow"] }, ctxFor("eval", kv()));
  assert.equal(result.reason, "pass-with-blocking-finding");
});

test("the read check is not tied to the verdict word: a PASS with undelivered on-demand skills is refused too", async () => {
  const result = await execute(
    {
      ...VERDICT,
      verdict: "PASS",
      skills: [
        ...VERDICT.skills,
        { skill: "outside-commenter", used: true, note: "they posted shell commands" },
      ],
    },
    ctxFor("live", kv()),
  );
  assert.equal(result.reason, "skill-not-read");
});

// --- the instructions that go with the checks -------------------------------------

const instructions = readFileSync("bot/instructions.md", "utf8");

test("instructions: step 5 keeps both recoverable refusals and tells the model what to do about skill-not-read", () => {
  const step = /5\. Call `post_verdict`[\s\S]*?\n6\. /.exec(instructions)?.[0] ?? "";
  assert.match(step, /pass-with-blocking-finding/);
  assert.match(step, /skill-not-read/);
  assert.match(step, /used: false/);
  assert.match(instructions, /Mark a skill `used: true` only if you opened its `SKILL\.md` this session/);
});

test("instructions: a reviewer's state comes from check_gate_state, and the Replit slot's identity rule matches lib/verdicts.ts", () => {
  const section = /## Reviewer state comes from the gate\n([\s\S]*?)\n## /.exec(instructions)?.[1] ?? "";
  assert.ok(section.length > 0, "the section is there");
  assert.match(section, /`check_gate_state` reports/);
  assert.match(section, /`missing`/);
  assert.match(section, /not recorded/i);
  assert.match(section, /Replit's is only a comment from\s+the owner account/);
  assert.match(section, /no GitHub App attribution at all/);
  assert.match(section, /bot account\s+such as `replit-review\[bot\]`/);
  // the code the prose describes
  const verdicts = readFileSync("bot/lib/verdicts.ts", "utf8");
  assert.match(verdicts, /comment\.user\?\.login === OWNER_LOGIN/);
  assert.match(verdicts, /comment\.performedViaGithubApp === null/);
  assert.match(verdicts, /isReplitReport\(comment\.body\)/);
});

test("instructions repeat the five owner rules, and each rule's heading is the owner-rules skill's own", () => {
  const skill = readFileSync("bot/skills/owner-rules/SKILL.md", "utf8");
  const headings = [...skill.matchAll(/^## (\d)\. (.+)$/gm)].map((m) => ({ n: m[1], title: (m[2] ?? "").replace(/\.$/, "") }));
  assert.equal(headings.length, 5);
  const inline = /## Owner rules, always in force\n([\s\S]*?)\n## /.exec(instructions)?.[1] ?? "";
  assert.ok(inline.length > 0, "the inline section is there");
  for (const { n, title } of headings) {
    const first = title.split(/[.,]/)[0] ?? title;
    assert.ok(inline.includes(`${n}. **${first}`), `rule ${n} (${first}) is repeated in instructions.md`);
  }
});

test("owner rule 1 says a reader must reject an empty snapshot itself, in the skill and in the instructions", () => {
  const skill = readFileSync("bot/skills/owner-rules/SKILL.md", "utf8");
  for (const [name, text] of [["skill", skill], ["instructions", instructions]] as const) {
    assert.match(text, /empty or zero `netuids`/, name);
    assert.match(text, /not a complete snapshot/, name);
  }
  assert.match(skill, /second layer/);
});

test("the adversarial-review skill makes the model multiply a bound out and convert steps to time before judging a budget", () => {
  const skill = readFileSync("bot/skills/adversarial-review/SKILL.md", "utf8");
  assert.match(skill, /## 3b\. Estimating cost you cannot time/);
  assert.match(skill, /`starts x K`/);
  assert.match(skill, /steps per\s+millisecond/);
  assert.match(skill, /Linear growth/);
  assert.match(skill, /inconclusive/);
});
