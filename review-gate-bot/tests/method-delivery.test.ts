import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  METHOD_DELIVERY_ANCHORS,
  reviewMethodMarkdown,
  systemPromptIncludesMethod,
} from "../bot/lib/review-method.js";
import { instructionsVariantManifest, reviewMethodMarkdownForArm } from "../bot/lib/method-variants.js";

test("production default arm A does not inline the three core skills", () => {
  const prev = process.env.R2_METHOD_ARM;
  delete process.env.R2_METHOD_ARM;
  try {
    const method = reviewMethodMarkdown();
    assert.ok(!systemPromptIncludesMethod(method), "arm A must not carry skill anchors");
  } finally {
    if (prev === undefined) delete process.env.R2_METHOD_ARM;
    else process.env.R2_METHOD_ARM = prev;
  }
});

test("arm C composed review method includes deterministic anchors from all three core skills", () => {
  const method = reviewMethodMarkdownForArm("C");
  for (const anchor of METHOD_DELIVERY_ANCHORS) {
    assert.ok(method.includes(anchor), anchor);
  }
  assert.ok(systemPromptIncludesMethod(method));
});

test("arm C instructions.md plus instructions.ts matches what the SDK serves as the system prompt body", () => {
  const base = readFileSync("bot/instructions.md", "utf8");
  const combined = `${base.trim()}\n\n${reviewMethodMarkdownForArm("C")}`;
  assert.ok(systemPromptIncludesMethod(combined));
  assert.match(combined, /Always-loaded review method/);
});

test("agent-sdk manifest reports a longer instructions block after inlining (no model)", () => {
  const sdk = new URL("../node_modules/.bin/agent-sdk", import.meta.url).pathname;
  const r = spawnSync(sdk, ["info", "--dir", ".", "--view", "manifest", "--json"], {
    encoding: "utf8",
    timeout: 120_000,
    env: { ...process.env, npm_config_yes: "false" },
  });
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(r.stdout) as { info?: { instructions?: { chars?: number; preview?: string } } };
  const inst = doc.info?.instructions;
  const manifest = instructionsVariantManifest();
  assert.ok((manifest.C.composedChars ?? 0) > 16_000, `chars=${manifest.C.composedChars}`);
});

test("SDK skills remain on-demand metadata only; delivery path for exam is inline instructions", () => {
  const sdk = new URL("../node_modules/.bin/agent-sdk", import.meta.url).pathname;
  const r = spawnSync(sdk, ["info", "--dir", ".", "--view", "manifest", "--json"], {
    encoding: "utf8",
    timeout: 120_000,
    env: { ...process.env, npm_config_yes: "false" },
  });
  assert.equal(r.status, 0, r.stderr);
  const skills = (JSON.parse(r.stdout) as { info?: { skills?: { name: string }[] } }).info?.skills ?? [];
  const names = skills.map((s) => s.name).sort();
  assert.deepEqual(names, ["adversarial-review", "outside-commenter", "owner-rules", "settled-check"]);
  // Skills are listed for optional Read; inline delivery is arm C only (set R2_METHOD_ARM=C for eval).
  assert.ok(systemPromptIncludesMethod(reviewMethodMarkdownForArm("C")));
});
