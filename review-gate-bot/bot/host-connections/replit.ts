import { defineConnection } from "@grok/agent-sdk/connections";

/**
 * Replit's remote MCP server, reached through the signed-in Cursor account.
 *
 * Why the Cursor-account form and not `{ url, oauth: true }`: the SDK docs say
 * `mcp oauth` tokens stay on the machine that authorized them, and that a
 * Cursor-hosted agent should add the server under MCP in the Cursor dashboard
 * and reach it through a `cursorAccount: true` connection. `oauth: true` would
 * work on a self-hosted serve but not on the deployment this bot is meant for.
 *
 * `tools` limits this host connection to the one tool the gate calls. The model
 * never sees it, so the model cannot ask Replit its own question or pick a
 * different replId. `lib/replit.ts` is the only caller.
 */
export default defineConnection({
  cursorAccount: true,
  servers: ["Replit"],
  tools: ["ask_question"],
});
