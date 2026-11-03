import assert from "node:assert/strict";
import { existsSync } from "node:fs";
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

test("fixture gate: npm oracle:check:fast is the executed-oracle regen entry (optional in CI)", () => {
  const pkg = JSON.parse(
    spawnSync("cat", [`${BOT_ROOT}/package.json`], { encoding: "utf8" }).stdout,
  ) as { scripts: Record<string, string> };
  assert.equal(pkg.scripts["oracle:check:fast"], "python3 evals/oracle-gen/gen.py --check --skip-behavior");
});
