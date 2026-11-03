import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  METHOD_ARMS,
  instructionsVariantManifest,
  reviewMethodMarkdownForArm,
} from "../bot/lib/method-variants.js";
import { OWNER_RULES_ALWAYS_IN_FORCE_BLOCK } from "../bot/lib/instruction-blocks.js";

test("arm A append is empty so SDK instructions match bot/instructions.md only", () => {
  const base = readFileSync(new URL("../bot/instructions.md", import.meta.url), "utf8").trim();
  const manifest = instructionsVariantManifest();
  assert.equal(reviewMethodMarkdownForArm("A"), "");
  assert.equal(manifest.A.appendChars, 0);
  assert.equal(manifest.A.composedChars, base.length);
  assert.equal(manifest.A.baseSha, createHash("sha256").update(base, "utf8").digest("hex"));
});

test("R2 arms A–D on PR-head base: distinct SHA256; A is control only", () => {
  const manifest = instructionsVariantManifest();
  assert.ok(manifest.A.baseChars >= 6785 && manifest.A.baseChars <= 6820, `baseChars=${manifest.A.baseChars}`);
  for (const arm of METHOD_ARMS) {
    assert.match(manifest[arm].sha256, /^[a-f0-9]{64}$/);
  }
  assert.equal(new Set(METHOD_ARMS.map((a) => manifest[a].sha256)).size, METHOD_ARMS.length);
  assert.equal(manifest.A.appendChars, 0);
  assert.equal(manifest.A.composedChars, manifest.A.baseChars);
  assert.ok(manifest.B.appendChars > 1000);
  assert.ok(manifest.C.composedChars > manifest.B.composedChars);
  assert.ok(manifest.D.composedChars > manifest.B.composedChars);
});

test("arm B is owner-rules block only; arm C is three skills; arm D adds reviewer-state", () => {
  assert.equal(reviewMethodMarkdownForArm("A"), "");
  assert.equal(reviewMethodMarkdownForArm("B"), OWNER_RULES_ALWAYS_IN_FORCE_BLOCK);
  const c = reviewMethodMarkdownForArm("C");
  assert.match(c, /Always-loaded review method \(R2 arm C\)/);
  assert.match(c, /### adversarial-review/);
  assert.match(c, /Picks readers serve only complete snapshots/);
  const d = reviewMethodMarkdownForArm("D");
  assert.match(d, /Reviewer state comes from the gate/);
  assert.match(d, /Owner rules, always in force/);
});

test("arm R is the r23 suite-shrink verdict rule only", () => {
  const r = reviewMethodMarkdownForArm("R");
  assert.match(r, /reduces what the recorded full-suite comparison actually checks/);
  assert.doesNotMatch(r, /Owner rules, always in force/);
});
