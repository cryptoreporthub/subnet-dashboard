import assert from "node:assert/strict";
import test from "node:test";
import {
  PRODUCTION_R2_METHOD_ARM_CHECK_PATHS,
  assertHostedLiveHasNoExamArmEnv,
  deployFilesMentioningR2MethodArm,
} from "../bot/lib/production-config.js";

test("production deploy config does not set R2_METHOD_ARM (fly.toml + bot/agent.ts)", () => {
  const hits = deployFilesMentioningR2MethodArm();
  assert.deepEqual(
    hits,
    [],
    `R2_METHOD_ARM must not appear in production deploy surfaces; checked: ${JSON.stringify(PRODUCTION_R2_METHOD_ARM_CHECK_PATHS)}; found: ${hits.join(", ")}`,
  );
});

test("assertHostedLiveHasNoExamArmEnv allows unset or A only", () => {
  const prev = process.env.R2_METHOD_ARM;
  try {
    delete process.env.R2_METHOD_ARM;
    assert.doesNotThrow(() => assertHostedLiveHasNoExamArmEnv());
    process.env.R2_METHOD_ARM = "A";
    assert.doesNotThrow(() => assertHostedLiveHasNoExamArmEnv());
    process.env.R2_METHOD_ARM = "F";
    assert.throws(() => assertHostedLiveHasNoExamArmEnv(), /R2_METHOD_ARM/);
  } finally {
    if (prev === undefined) {
      delete process.env.R2_METHOD_ARM;
    } else {
      process.env.R2_METHOD_ARM = prev;
    }
  }
});
