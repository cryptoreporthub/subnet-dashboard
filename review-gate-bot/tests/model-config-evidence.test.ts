import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const BOT = new URL("..", import.meta.url).pathname;
const REPO = new URL("../..", import.meta.url).pathname;
const SDK = join(BOT, "node_modules/.bin/agent-sdk");

test("R0.5 model config: UNVERIFIED whether bare effort disables max reasoning at runtime", () => {
  const agent1522 = spawnSync(
    "git",
    ["show", "origin/agent/pr-1522-exam-r6-fixes:review-gate-bot/bot/agent.ts"],
    { cwd: REPO, encoding: "utf8" },
  );
  assert.equal(agent1522.status, 0, agent1522.stderr);
  assert.match(agent1522.stdout, /id: "effort"/);

  const tmp = mkdtempSync(join(tmpdir(), "rg-effort-"));
  cpSync(BOT, tmp, { recursive: true });
  writeFileSync(join(tmp, "bot/agent.ts"), readFileSync(join(tmp, "bot/agent.ts"), "utf8").replace(/reasoning_effort/g, "effort"));
  const validate = spawnSync(SDK, ["validate", "--dir", tmp], { encoding: "utf8" });
  assert.equal(validate.status, 0, validate.stdout + validate.stderr);
  assert.match(validate.stdout + validate.stderr, /no diagnostics/i);

  // ponytail: no DeepSeek registry API in CI — production risk stays OPEN until a host error or registry dump is captured.
  assert.ok(true, "UNVERIFIED: SDK 0.3.0 validate accepts effort; runtime may ignore it");
});

test("R0.5: R0 branch documents reasoning_effort in agent.ts (human override)", () => {
  assert.match(readFileSync(join(BOT, "bot/agent.ts"), "utf8"), /reasoning_effort/);
  const validate = spawnSync(SDK, ["validate", "--dir", BOT], { encoding: "utf8" });
  assert.equal(validate.status, 0, validate.stderr);
});
