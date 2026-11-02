import { defineAgent } from "@grok/agent-sdk";

export default defineAgent({
  model: { id: "composer-2.5", params: [{ id: "fast", value: "false" }] },
  local: { sandbox: true },
  description:
    "Mission Control review gate for cryptoreporthub/subnet-dashboard. Adversarial PR review, deterministic gate order, automatic @cursor/@ditto/@replit tagging. Never merges, deploys, restarts, sets secrets or labels.",
  hosting: {
    egressDomains: ["api.github.com", "mcp.replit.com", "*.blob.core.windows.net", "*.actions.githubusercontent.com"],
    secretNames: ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET", "GITHUB_APP_INSTALLATION_ID"],
  },
  tools: [],
  concurrency: { maxRunningTurns: 4 },
});
