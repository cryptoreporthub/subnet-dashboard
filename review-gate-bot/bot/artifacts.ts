import { defineArtifacts } from "@grok/agent-sdk/artifacts";
import { z } from "zod";

/**
 * Durable gate ledger. One row per `(PR, head SHA)` for MC's own verdict, so a
 * later process can answer "was this head reviewed" without re-reading every
 * comment on the PR.
 *
 * `agentTool` is left off: the model must not be able to write the ledger, or a
 * verdict could be recorded without being posted.
 */
export default defineArtifacts({
  kinds: {
    "head-verdict": {
      description: "MC's formal verdict for one pull request head SHA.",
      schema: z.object({
        reviewer: z.literal("mc"),
        verdict: z.enum(["PASS", "MODIFY", "FAIL"]),
        headSha: z.string(),
        pr: z.string(),
        redactedNames: z.array(z.string()),
      }),
    },
  },
  agentTool: false,
});
