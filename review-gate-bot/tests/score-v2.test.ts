import assert from "node:assert/strict";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("score-v2 loads expected table and scores a synthetic run", () => {
  const sample = {
    results: [
      {
        id: "review-gate-hard/planted-grace-seconds/1",
        toolCalls: [{ toolName: "post_verdict", input: { verdict: "MODIFY", body: "MODIFY\noverflow" } }],
      },
    ],
  };
  const dir = mkdtempSync(join(tmpdir(), "score-v2-"));
  const path = join(dir, "sample.json");
  writeFileSync(path, JSON.stringify(sample));
  const botRoot = new URL("..", import.meta.url).pathname;
  const r = spawnSync("python3", ["evals/score-v2.py", path], {
    encoding: "utf8",
    cwd: botRoot,
  });
  assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout.trim()) as {
    retiredMetric?: string;
    byFamily?: Record<string, unknown>;
  };
  assert.equal(out.retiredMetric, "pooled_semantic_catch_over_63_total");
  assert.ok(out.byFamily);
});

test("fixture gate pytest module collects (R0.2)", () => {
  const repoRoot = new URL("../..", import.meta.url).pathname;
  const py = existsSync(`${repoRoot}/.venv/bin/python`) ? `${repoRoot}/.venv/bin/python` : "python3";
  const r = spawnSync(py, ["-m", "pytest", "-q", "review-gate-bot/evals/fixture-gate/test_gate.py", "--collect-only"], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});
