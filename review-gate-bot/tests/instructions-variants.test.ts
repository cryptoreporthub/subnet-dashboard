import assert from "node:assert/strict";
import test from "node:test";
import {
  METHOD_ARMS,
  instructionsVariantManifest,
  reviewMethodMarkdownForArm,
} from "../bot/lib/method-variants.js";
import { OWNER_RULES_ALWAYS_IN_FORCE_BLOCK } from "../bot/lib/instruction-blocks.js";
import { systemPromptIncludesMethod } from "../bot/lib/review-method.js";

test("R2 arms A–D on PR-head base: distinct SHA256; A is control only", () => {
  const manifest = instructionsVariantManifest();
  assert.ok(manifest.A.baseChars >= 6785 && manifest.A.baseChars <= 6820, `baseChars=${manifest.A.baseChars}`);
  for (const arm of METHOD_ARMS) {
    assert.match(manifest[arm].sha256, /^[a-f0-9]{64}$/);
  }
  assert.equal(new Set(METHOD_ARMS.map((a) => manifest[a].sha256)).size, 4);
  assert.equal(manifest.A.appendChars, 0);
  assert.equal(manifest.A.composedChars, manifest.A.baseChars);
  assert.ok(manifest.B.appendChars > 1000);
  assert.ok(manifest.C.composedChars > manifest.B.composedChars);
  assert.ok(manifest.D.composedChars > manifest.B.composedChars);
});

test("arm B is owner-rules block only; arm C is three skills; arm D adds reviewer-state", () => {
  assert.equal(reviewMethodMarkdownForArm("A"), "");
  assert.equal(reviewMethodMarkdownForArm("B"), OWNER_RULES_ALWAYS_IN_FORCE_BLOCK);
  assert.ok(systemPromptIncludesMethod(reviewMethodMarkdownForArm("C")));
  const d = reviewMethodMarkdownForArm("D");
  assert.match(d, /Reviewer state comes from the gate/);
  assert.match(d, /Owner rules, always in force/);
});
