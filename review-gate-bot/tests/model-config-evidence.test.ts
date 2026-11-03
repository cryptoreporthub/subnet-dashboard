import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const BOT = new URL("..", import.meta.url).pathname;
const REPO = new URL("../..", import.meta.url).pathname;
const SDK = join(BOT, "node_modules/.bin/agent-sdk");

test("R0.5: PR #1522 head uses effort; pinned SDK 0.3.0 validate reports no diagnostics", () => {
  const agent1522 = spawnSync(
    "git",
    ["show", "origin/agent/pr-1522-exam-r6-fixes:review-gate-bot/bot/agent.ts"],
    { cwd: REPO, encoding: "utf8" },
  );
  assert.equal(agent1522.status, 0, agent1522.stderr);
  assert.match(agent1522.stdout, /id: "effort"/);
  assert.doesNotMatch(agent1522.stdout, /reasoning_effort/);

  const tmp = mkdtempSync(join(tmpdir(), "rg-effort-"));
  cpSync(BOT, tmp, { recursive: true });
  const agentPath = join(tmp, "bot/agent.ts");
  let src = readFileSync(agentPath, "utf8");
  src = src.replace(/reasoning_effort/g, "effort");
  writeFileSync(agentPath, src);

  const validate = spawnSync(SDK, ["validate", "--dir", tmp], { encoding: "utf8" });
  assert.equal(validate.status, 0, validate.stdout + validate.stderr);
  assert.match(validate.stdout + validate.stderr, /no diagnostics/i);
});

test("R0.5: R0 branch uses reasoning_effort=max and validate is clean", () => {
  const agent = readFileSync(join(BOT, "bot/agent.ts"), "utf8");
  assert.match(agent, /reasoning_effort/);
  assert.doesNotMatch(agent, /id: "effort"/);
  const validate = spawnSync(SDK, ["validate", "--dir", BOT], { encoding: "utf8" });
  assert.equal(validate.status, 0, validate.stderr);
  assert.match(validate.stdout + validate.stderr, /no diagnostics/i);
});

test("R0.5: pinned agent-sdk 0.3.0 validate does not diagnose bare effort (production risk)", () => {
  const tmp = mkdtempSync(join(tmpdir(), "rg-effort-lenient-"));
  cpSync(BOT, tmp, { recursive: true });
  const agentPath = join(tmp, "bot/agent.ts");
  writeFileSync(agentPath, readFileSync(agentPath, "utf8").replace(/reasoning_effort/g, "effort"));
  const validate = spawnSync(SDK, ["validate", "--dir", tmp], { encoding: "utf8" });
  assert.equal(validate.status, 0, validate.stdout + validate.stderr);
  assert.match(validate.stdout + validate.stderr, /no diagnostics/i);
  assert.match(readFileSync(join(BOT, "bot/agent.ts"), "utf8"), /The registry's parameter is `reasoning_effort`/);
});
