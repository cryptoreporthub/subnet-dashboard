import assert from "node:assert/strict";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("score-v2: first posted:true verdict only (refused posts ignored)", () => {
  const sample = {
    results: [
      {
        id: "review-gate-hard/miss-jwt-scrub-slow/1",
        toolCalls: [
          {
            toolName: "post_verdict",
            input: { verdict: "PASS", body: "PASS\nbad" },
            output: JSON.stringify({ posted: false, reason: "pass-with-unmeasured-perf-claim", verdict: "PASS" }),
          },
          {
            toolName: "post_verdict",
            input: { verdict: "MODIFY", body: "MODIFY\nok" },
            output: JSON.stringify({ posted: true, reason: "eval", verdict: "MODIFY" }),
          },
        ],
      },
    ],
  };
  const dir = mkdtempSync(join(tmpdir(), "score-v2-accepted-"));
  const path = join(dir, "sample.json");
  writeFileSync(path, JSON.stringify(sample));
  const botRoot = new URL("..", import.meta.url).pathname;
  const r = spawnSync("python3", ["evals/score-v2.py", path], { encoding: "utf8", cwd: botRoot });
  assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout.trim()) as { rows: { actual: string }[]; byFamily?: Record<string, { catch: number }> };
  assert.equal(out.rows[0]?.actual, "MODIFY");
});

test("score-v2 loads expected table and scores a synthetic run", () => {
  const sample = {
    results: [
      {
        id: "review-gate-hard/planted-grace-seconds/1",
        toolCalls: [
          {
            toolName: "post_verdict",
            input: { verdict: "MODIFY", body: "MODIFY\noverflow" },
            output: JSON.stringify({ posted: true, verdict: "MODIFY" }),
          },
        ],
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
