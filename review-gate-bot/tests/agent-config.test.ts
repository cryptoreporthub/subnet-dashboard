import assert from "node:assert/strict";
import test from "node:test";
import agent from "../bot/agent.js";

test("the model gets no built-in tools, so it cannot shell out, read the host or edit files", () => {
  const config = agent as unknown as { tools?: unknown };
  assert.ok(Array.isArray(config.tools), "an omitted allowlist means the full standard toolset, shell included");
  assert.deepEqual(config.tools, []);
});

test("egress lists no host beyond GitHub, Replit and the Actions artifact storage", () => {
  const hosts = (agent as unknown as { hosting: { egressDomains: string[] } }).hosting.egressDomains;
  assert.deepEqual([...hosts].sort(), [
    "*.actions.githubusercontent.com",
    "*.blob.core.windows.net",
    "api.github.com",
    "mcp.replit.com",
  ]);
});

test("the tool surface is the seven named tools, and the three that look at the repo only read", async () => {
  const { readdir } = await import("node:fs/promises");
  const names = (await readdir(new URL("../bot/tools/", import.meta.url)))
    .filter((file) => file.endsWith(".ts"))
    .map((file) => file.replace(/\.ts$/, ""))
    .sort();
  assert.deepEqual(names, [
    "check_gate_state",
    "compare_suite_runs",
    "get_pr_diff",
    "get_pr_head",
    "list_repo_files",
    "post_verdict",
    "read_repo_file",
  ]);
  for (const name of ["get_pr_diff", "list_repo_files", "read_repo_file", "get_pr_head", "check_gate_state"]) {
    const tool = (await import(`../bot/tools/${name}.js`)).default as { effect?: string };
    assert.equal(tool.effect, "read", name);
  }
});
