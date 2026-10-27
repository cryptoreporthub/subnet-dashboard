import { defineAgent } from "@grok/agent-sdk";

/**
 * Review-only agent. `local.sandbox` is deliberately omitted: this bot reviews
 * code and posts prose, and the amendment asks for no sandboxing.
 *
 * `hosting.secretNames` is declarative documentation only — values are never
 * in the repo. See README.md for the exact names and how Joshua sets them.
 */
export default defineAgent({
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
  // tool off; the bot's tools in `bot/tools/` reach the model over MCP, which the SDK adds.
  tools: [],
  concurrency: { maxRunningTurns: 4 },
});
