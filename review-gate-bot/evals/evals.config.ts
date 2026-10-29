import { defineEvalConfig } from "@grok/agent-sdk/evals";
import { installReasoningCoalescing } from "./coalesce-reasoning.js";

// The eval server runs in this process: merge reasoning token chunks so the event log stays linear in
// the reasoning length (see coalesce-reasoning.ts). Without it a max-effort review can write 700+ MB.
await installReasoningCoalescing();

export default defineEvalConfig({
  maxConcurrency: 1,
  judge: { model: { id: "grok-4.7", params: [{ id: "reasoning_effort", value: "xhigh" }] } },
});
