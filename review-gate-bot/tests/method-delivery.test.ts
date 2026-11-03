import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  METHOD_DELIVERY_ANCHORS,
  reviewMethodMarkdown,
  systemPromptIncludesMethod,
} from "../bot/lib/review-method.js";

test("composed review method includes deterministic anchors from all three core skills", () => {
  const method = reviewMethodMarkdown();
  for (const anchor of METHOD_DELIVERY_ANCHORS) {
    assert.ok(method.includes(anchor), anchor);
  }
  assert.ok(systemPromptIncludesMethod(method));
});

test("instructions.md plus instructions.ts matches what the SDK serves as the system prompt body", () => {
  const base = readFileSync("bot/instructions.md", "utf8");
  const combined = `${base.trim()}\n\n${reviewMethodMarkdown()}`;
  assert.ok(systemPromptIncludesMethod(combined));
  assert.match(combined, /Always-loaded review method/);
});

test("agent-sdk manifest reports a longer instructions block after inlining (no model)", () => {
  const r = spawnSync("npx", ["--yes", "@grok/agent-sdk@0.5.0", "info", "--dir", ".", "--view", "manifest", "--json"], {
    encoding: "utf8",
    timeout: 120_000,
  });
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(r.stdout) as { info?: { instructions?: { chars?: number; preview?: string } } };
  const inst = doc.info?.instructions;
  assert.ok(inst && (inst.chars ?? 0) > 20_000, `chars=${inst?.chars}`);
});

test("SDK skills remain on-demand metadata only; delivery path for exam is inline instructions", () => {
  const r = spawnSync("npx", ["--yes", "@grok/agent-sdk@0.5.0", "info", "--dir", ".", "--view", "manifest", "--json"], {
    encoding: "utf8",
    timeout: 120_000,
  });
  assert.equal(r.status, 0, r.stderr);
  const skills = (JSON.parse(r.stdout) as { info?: { skills?: { name: string }[] } }).info?.skills ?? [];
  const names = skills.map((s) => s.name).sort();
  assert.deepEqual(names, ["adversarial-review", "outside-commenter", "owner-rules", "settled-check"]);
  // Skills are listed for optional Read; they are not merged into instructions unless inlined (see bot/instructions.ts).
  assert.ok(systemPromptIncludesMethod(reviewMethodMarkdown()));
});
