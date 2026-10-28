import { defineAgent } from "@grok/agent-sdk";

/**
 * Review-only agent: it reviews code and posts prose. `local.sandbox` is on for one reason only,
 * to confine the `read` tool the skills need (see `tools` below); the bot runs no code.
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
  // with whatever credentials the host holds. The SDK still adds `mcp`, because the
  // bot's own tools in `bot/tools/` reach the model through it; the MCP meta-tools
  // (list, call) the model sees are that transport, and the SDK has no switch to hide
  // them. What they can reach is what this folder attaches, which is nothing: no
  // `bot/mcp-connections/`, and the Replit connection is a host connection the model
  // cannot see (tests/agent-config.test.ts pins both).
  //
  // `read` is the one built-in tool left on, and only so the model can open its own
  // skills (`adversarial-review`, `owner-rules`, `settled-check`). With `tools: []`
  // the skill files were unreachable and the bot reviewed without its checklists
  // (eval of 50e231f3: 36 of 37 posted runs said the skill file was unreadable).
  // No shell, no edit/delete/write, no grep/glob/ls, no web tools, no subagents.
  //
  // `read` alone would reach any path the serve process can (measured with sandbox off:
  // /etc/passwd and /proc/self/cmdline read back), and on a host that holds secrets that
  // includes the process environment. `local.sandbox` makes the file tools refuse a path
  // outside the session workspace, which holds the skills and nothing else (measured:
  // /etc/passwd, /proc/self/cmdline, ../../etc/passwd and /home all refused with
  // "Path is outside the workspace", the skill still read). The bot's own tools, which
  // reach the model over MCP, run unchanged. tests/agent-config.test.ts pins both.
  tools: ["read"],
  local: { sandbox: true },
  concurrency: { maxRunningTurns: 4 },
});
