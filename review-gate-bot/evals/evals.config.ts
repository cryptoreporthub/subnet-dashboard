import { defineEvalConfig } from "@grok/agent-sdk/evals";

export default defineEvalConfig({
  maxConcurrency: 6,
  judge: { model: "gpt-5.4-mini" },
});
