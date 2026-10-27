import { defineEvalConfig } from "@grok/agent-sdk/evals";

export default defineEvalConfig({
  maxConcurrency: 6,
  judge: { model: "glm-5.3-flash" },
});
