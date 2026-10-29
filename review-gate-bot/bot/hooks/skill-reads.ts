import { defineHook } from "@grok/agent-sdk/hooks";
import { recordSkillReads, skillsOpenedBy } from "../lib/skill-reads.js";

/**
 * Records which of the bot's skills a session opened, so `post_verdict` can check the Skills table against it
 * (`lib/skill-reads.ts`). Observes only: it never changes a turn. A handler that throws is logged and skipped by the
 * host, and a missing record makes the table's `used` claim fail the check, which is the safe direction.
 */
export default defineHook({
  events: {
    async "actions.requested"(event, ctx) {
      const opened = skillsOpenedBy(event.data.calls);
      if (opened.length === 0) {
        return;
      }
      await recordSkillReads(ctx.host.kv, ctx.session.id, opened);
    },
  },
});
