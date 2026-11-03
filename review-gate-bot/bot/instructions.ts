import { defineInstructions } from "@grok/agent-sdk";
import { reviewMethodMarkdown } from "./lib/review-method.js";

export default defineInstructions({
  markdown: reviewMethodMarkdown(),
});
