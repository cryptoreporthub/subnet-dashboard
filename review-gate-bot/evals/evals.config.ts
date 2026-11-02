import { defineEvalConfig } from "@grok/agent-sdk/evals";
import { installReasoningCoalescing } from "./coalesce-reasoning.js";

// The eval server runs in this process: merge reasoning token chunks so the event log stays linear in
// the reasoning length (see coalesce-reasoning.ts). Without it a max-effort review can write 700+ MB.
await installReasoningCoalescing();

export default defineEvalConfig({
  maxConcurrency: 6,
  // Joshua/MC: Composer NORMAL only — never composer-2.5-fast; fast param false = slow/normal seat.
  judge: { model: { id: "composer-2.5", params: [{ id: "fast", value: "false" }] } },
});
