import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  METHOD_ARMS,
  instructionsVariantManifest,
  reviewMethodMarkdownForArm,
} from "../bot/lib/method-variants.js";
import { systemPromptIncludesMethod } from "../bot/lib/review-method.js";

test("R2 instruction arms: none, owner-adv5, all-three differ in SHA256 and char counts", () => {
  const base = readFileSync("bot/instructions.md", "utf8");
  const manifest = instructionsVariantManifest(base);
  for (const arm of METHOD_ARMS) {
    assert.ok(manifest[arm].composedChars >= 0);
    assert.match(manifest[arm].sha256, /^[a-f0-9]{64}$/);
  }
  const shas = METHOD_ARMS.map((a) => manifest[a].sha256);
  assert.equal(new Set(shas).size, 3, "each arm must have a distinct composed SHA256");
  assert.equal(manifest.none.methodChars, 0);
  assert.ok(manifest["all-three"].composedChars > manifest["owner-adv5"].composedChars);
  assert.ok(manifest["owner-adv5"].composedChars > manifest.none.composedChars);
});

test("all-three arm includes method anchors; owner-adv5 includes owner + adv §5 only", () => {
  assert.ok(systemPromptIncludesMethod(reviewMethodMarkdownForArm("all-three")));
  const partial = reviewMethodMarkdownForArm("owner-adv5");
  assert.match(partial, /Picks readers serve only complete snapshots/);
  assert.match(partial, /Hunt for one bug the PR does not mention/);
  assert.doesNotMatch(partial, /## 3b\. Estimating cost you cannot time/);
  assert.equal(reviewMethodMarkdownForArm("none"), "");
});
