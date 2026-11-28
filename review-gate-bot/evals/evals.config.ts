import { defineEvalConfig } from "@grok/agent-sdk/evals";

export default defineEvalConfig({
  maxConcurrency: 6,
  judge: { model: { id: "grok-4.7", params: [{ id: "effort", value: "high" }] } },
});
