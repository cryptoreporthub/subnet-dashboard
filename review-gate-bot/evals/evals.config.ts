import { defineEvalConfig } from "@grok/agent-sdk/evals";

export default defineEvalConfig({
  maxConcurrency: 6,
  judge: { model: "deepseek-v41-flash-1017" },
});
