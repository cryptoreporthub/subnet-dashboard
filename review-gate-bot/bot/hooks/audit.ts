import { defineHook } from "@grok/agent-sdk/hooks";

/**
 * Observe-only audit mirror.
 *
 * Mirrors the tool calls that matter to the gate — verdict posts and gate reads
 * — into the log with secret names redacted. A hook cannot change a turn, so
 * this is evidence, never a control. Writes nothing to GitHub.
 */
export default defineHook({
  events: {
    async "action.result"(event, ctx) {
      if (ctx.session.purpose === "eval") {
        return;
      }
      const watch = new Set(["post_verdict", "check_gate_state", "compare_suite_runs", "get_pr_head"]);
      if (!watch.has(event.data.toolName)) {
        return;
      }
      console.log(
        JSON.stringify({
          at: new Date().toISOString(),
          session: ctx.session.id,
          channel: ctx.channel.id,
          tool: event.data.toolName,
          isError: event.data.isError === true,
        }),
      );
    },
  },
});
