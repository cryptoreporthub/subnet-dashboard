import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";

const REPO_ROOT = new URL("../..", import.meta.url).pathname;
const BOT_ROOT = new URL("..", import.meta.url).pathname;
const VENV_PYTHON = `${REPO_ROOT}/.venv/bin/python`;

function pythonBin(): string {
  return existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3";
}

test("fixture gate: structural pytest module (oracle pins, no tautologies)", () => {
  const py = pythonBin();
  const r = spawnSync(
    py,
    ["-m", "pytest", "-q", "review-gate-bot/evals/fixture-gate/test_gate.py"],
    {
      cwd: REPO_ROOT,
      encoding: "utf8",
      timeout: 120_000,
    },
  );
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("fixture gate: ONE fail-closed npm script exists", () => {
  const pkg = JSON.parse(readFileSync(`${BOT_ROOT}/package.json`, "utf8")) as { scripts: Record<string, string> };
  assert.equal(pkg.scripts["fixture-gate"], "python3 evals/fixture-gate/run_gate.py");
});
