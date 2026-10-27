import { defineArtifacts } from "@grok/agent-sdk/artifacts";
import { z } from "zod";

/**
 * Durable gate ledger. One row per `(PR, head SHA)` for MC's own verdict.
 *
 * **This ledger is evidence, not gate input.** The gate reads MC's verdict from
 * the marker comment on the PR (`lib/verdicts.ts` → `ownMarkerHead`), because a
 * published comment is what a reviewer can see and check. The ledger used to
 * disagree with GitHub: `post_verdict` wrote a row even when the comment was
 * suppressed, so a later reader could find a verdict the PR never showed. It is
 * now written only when the post actually landed, and it carries the comment id
 * so a reader can confirm the two agree.
 *
 * `agentTool` is left off: the model must not be able to write the ledger, or a
 * verdict could be recorded without being posted.
 */
export default defineArtifacts({
  kinds: {
    "head-verdict": {
      description: "MC's formal verdict for one pull request head SHA. Evidence for the comment; the gate reads the comment.",
      schema: z.object({
        reviewer: z.literal("mc"),
        verdict: z.enum(["PASS", "MODIFY", "FAIL"]),
        headSha: z.string(),
        pr: z.string(),
        /** The comment this row describes. Absent would mean a row with no post. */
        commentId: z.number().nullable(),
        redactedNames: z.array(z.string()),
      }),
    },
  },
  agentTool: false,
});
