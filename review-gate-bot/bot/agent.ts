import { defineAgent } from "@grok/agent-sdk";

/**
 * Review-only agent. `local.sandbox` is deliberately omitted: this bot reviews
 * code and posts prose, and the amendment asks for no sandboxing.
 *
 * `hosting.secretNames` is declarative documentation only — values are never
 * in the repo. See README.md for the exact names and how Joshua sets them.
 */
export default defineAgent({
  // Pinned so an SDK upgrade cannot change how the gate judges. Joshua chose DeepSeek at
  // maximum reasoning effort for the bot (#1513). This is a human override of
  // model-guide.md, which is why that guide names this bot as its one exception.
  model: {
    id: "deepseek-v41-flash-1017",
    params: [{ id: "effort", value: "max" }],
  },
  description:
    "Mission Control review gate for cryptoreporthub/subnet-dashboard. Adversarial PR review, deterministic gate order, automatic @cursor/@ditto/@replit tagging. Never merges, deploys, restarts, sets secrets or labels.",
  hosting: {
    // GitHub answers an artifact download with a 302 to a signed URL on Azure
    // blob storage (measured: productionresultssa19.blob.core.windows.net), so
    // that host family is needed for the suite comparison. `lib/runner.ts`
    // refuses any redirect host outside this family.
    egressDomains: ["api.github.com", "mcp.replit.com", "*.blob.core.windows.net", "*.actions.githubusercontent.com"],
    secretNames: ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET", "GITHUB_APP_INSTALLATION_ID"],
  },
  // An omitted allowlist means the full standard toolset, shell included, run
  // with whatever credentials the host holds. An empty one turns every built-in
  // tool off. The SDK still adds `mcp`, because the bot's own tools in
  // `bot/tools/` reach the model through it; the MCP meta-tools (list, call)
  // the model sees are that transport, and the SDK has no switch to hide them.
  // What they can reach is what this folder attaches, which is nothing: no
  // `bot/mcp-connections/`, and the Replit connection is a host connection the
  // model cannot see (tests/agent-config.test.ts pins both).
  tools: [],
  concurrency: { maxRunningTurns: 4 },
});
