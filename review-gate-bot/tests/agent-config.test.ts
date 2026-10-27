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
