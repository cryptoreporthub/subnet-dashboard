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
    egressDomains: ["api.github.com", "mcp.replit.com"],
    secretNames: ["GITHUB_TOKEN"],
  },
  concurrency: { maxRunningTurns: 4 },
});
