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

test("the tool surface is the six named tools, and the four that look at the PR or repo only read", async () => {
  const { readdir } = await import("node:fs/promises");
  const names = (await readdir(new URL("../bot/tools/", import.meta.url)))
    .filter((file) => file.endsWith(".ts"))
    .map((file) => file.replace(/\.ts$/, ""))
    .sort();
  assert.deepEqual(names, [
    "check_gate_state",
    "compare_suite_runs",
    "get_pr_diff",
    "list_repo_files",
    "post_verdict",
    "read_repo_file",
  ]);
  for (const name of ["get_pr_diff", "list_repo_files", "read_repo_file", "check_gate_state"]) {
    const tool = (await import(`../bot/tools/${name}.js`)).default as { effect?: string };
    assert.equal(tool.effect, "read", name);
  }
});

test("the channel is the Simi-Revision App: named secrets, no Cursor-account identity, checks on", async () => {
  const { getGitHubChannelOptions } = await import("@grok/agent-sdk/channels/github");
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  assert.equal(options?.cursorAccount, undefined, "cursorAccount would make the bot post as the signed-in user");
  assert.equal(options?.botName, "simi-revision");
  assert.equal(options?.checks, true);
  assert.deepEqual(options?.credentials, {
    appId: { secretName: "GITHUB_APP_ID" },
    privateKey: { secretName: "GITHUB_APP_PRIVATE_KEY" },
    webhookSecret: { secretName: "GITHUB_WEBHOOK_SECRET" },
  });
});

test("every secret the channel names is declared for deploy, and no token is", () => {
  const names = (agent as unknown as { hosting: { secretNames: string[] } }).hosting.secretNames;
  for (const name of ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET"]) {
    assert.ok(names.includes(name), name);
  }
  assert.ok(!names.includes("GITHUB_TOKEN"), "a personal token would let the bot post as someone else");
});

test("the model is pinned, not left to the SDK default", () => {
  // Joshua's decision (#1513): the bot runs on DeepSeek at maximum reasoning effort.
  assert.deepEqual((agent as unknown as { model?: unknown }).model, {
    id: "deepseek-v41-flash-1017",
    params: [{ id: "effort", value: "max" }],
  });
});

test("the eval judge is a different model from the bot, so it never grades its own answers", async () => {
  const { default: evals } = await import("../evals/evals.config.js");
  const judge = (evals as unknown as { judge: { model: { id: string; params: { id: string; value: string }[] } } }).judge.model;
  assert.equal(judge.id, "grok-4.7");
  assert.deepEqual(judge.params, [{ id: "effort", value: "high" }]);
  assert.notEqual(judge.id, (agent as unknown as { model: { id: string } }).model.id);
});

test("the model reaches no MCP server but the bot's own: nothing is attached for the model to list", async () => {
  const { readdir } = await import("node:fs/promises");
  const root = new URL("../bot/", import.meta.url);
  const exists = async (dir: string) => (await readdir(root)).includes(dir);
  assert.equal(await exists("mcp-connections"), false, "an attached connection is model-visible");
  const hosted = await readdir(new URL("host-connections/", root));
  assert.deepEqual(hosted, ["replit.ts"], "host connections are invisible to the model, and only Replit is wired");
});
