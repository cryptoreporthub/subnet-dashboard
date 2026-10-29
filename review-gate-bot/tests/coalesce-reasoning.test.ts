import assert from "node:assert/strict";
import { test } from "node:test";
import { coalesceReasoning, FLUSH_CHARS } from "../evals/coalesce-reasoning.js";

type Ev = { type: string; data: Record<string, unknown> };

// The real mapper, loaded the way evals.config.ts loads it. Each test patches a private subclass prototype
// so the shared SDK class is only patched by the config.
async function realMapper(): Promise<new (emit: (e: Ev) => void) => { handleUpdate(u: unknown): void }> {
  const url = new URL("../node_modules/@grok/agent-sdk/dist/internal/event-mapper.js", import.meta.url).href;
  const mod = (await import(url)) as { TurnEventMapper: new (emit: (e: Ev) => void) => { handleUpdate(u: unknown): void } };
  class Sub extends mod.TurnEventMapper {}
  coalesceReasoning(Sub.prototype as never);
  return Sub;
}

const bytes = (events: Ev[]) => events.reduce((n, e) => n + JSON.stringify(e).length, 0);

test("one reasoning block of 60 KB written as 20-char chunks stays linear, with the same text", async () => {
  const Sub = await realMapper();
  const events: Ev[] = [];
  const m = new Sub((e) => events.push(e));
  const chunk = "reasoning chunk text";
  const n = 3000; // 60,000 characters
  for (let i = 0; i < n; i++) m.handleUpdate({ type: "thinking-delta", text: chunk });
  m.handleUpdate({ type: "thinking-completed", thinkingDurationMs: 5 });
  const appended = events.filter((e) => e.type === "reasoning.appended");
  // Unpatched: 3000 events carrying a cumulative text, about 90 MB. Patched: at most one event per 4 KB.
  assert.ok(appended.length <= Math.ceil((n * chunk.length) / FLUSH_CHARS) + 1, `events: ${appended.length}`);
  assert.ok(bytes(events) < 2_000_000, `bytes: ${bytes(events)}`);
  const joined = appended.map((e) => e.data.delta).join("");
  assert.equal(joined, chunk.repeat(n), "no reasoning text is lost or reordered");
  assert.equal(appended.at(-1)!.data.text, chunk.repeat(n), "the cumulative text on the last event is the full reasoning");
  assert.equal(events.at(-1)!.type, "reasoning.completed", "completion still follows the last text");
});

test("pending reasoning is flushed before a tool call or completion, never after", async () => {
  const Sub = await realMapper();
  const events: Ev[] = [];
  const m = new Sub((e) => events.push(e));
  m.handleUpdate({ type: "thinking-delta", text: "short thought" });
  assert.equal(events.length, 0, "below the threshold the text is held");
  m.handleUpdate({ type: "thinking-completed", thinkingDurationMs: 1 });
  assert.deepEqual(events.map((e) => e.type), ["reasoning.appended", "reasoning.completed"]);
  assert.equal(events[0]!.data.text, "short thought");
});

test("two mappers do not share pending text", async () => {
  const Sub = await realMapper();
  const a: Ev[] = [];
  const b: Ev[] = [];
  const ma = new Sub((e) => a.push(e));
  const mb = new Sub((e) => b.push(e));
  ma.handleUpdate({ type: "thinking-delta", text: "A" });
  mb.handleUpdate({ type: "thinking-delta", text: "B" });
  ma.handleUpdate({ type: "thinking-completed", thinkingDurationMs: 1 });
  mb.handleUpdate({ type: "thinking-completed", thinkingDurationMs: 1 });
  assert.equal(a[0]!.data.text, "A");
  assert.equal(b[0]!.data.text, "B");
});

test("patching twice wraps once", async () => {
  const proto = { handleUpdate(_u: unknown) {} };
  assert.equal(coalesceReasoning(proto as never), true);
  const first = proto.handleUpdate;
  assert.equal(coalesceReasoning(proto as never), false);
  assert.equal(proto.handleUpdate, first);
});

test("before: the unpatched SDK mapper writes the reasoning text once per chunk (the quadratic log)", async () => {
  const url = new URL("../node_modules/@grok/agent-sdk/dist/internal/event-mapper.js", import.meta.url).href;
  const mod = (await import(url)) as { TurnEventMapper: new (emit: (e: Ev) => void) => { handleUpdate(u: unknown): void } };
  class Plain extends mod.TurnEventMapper {} // not patched
  const events: Ev[] = [];
  const m = new Plain((e) => events.push(e));
  for (let i = 0; i < 3000; i++) m.handleUpdate({ type: "thinking-delta", text: "reasoning chunk text" });
  const carried = events.reduce((n, e) => n + String(e.data.text).length, 0);
  assert.equal(events.length, 3000);
  assert.ok(carried > 80_000_000, `cumulative text carried by the events: ${carried}`);
});
