import { defineInstructions } from "@grok/agent-sdk";
import { methodArmFromEnv, reviewMethodMarkdownForArm } from "./lib/method-variants.js";

/** R2 arms: set `R2_METHOD_ARM` to `none` | `owner-adv5` | `all-three` (default). */
export default defineInstructions({
  markdown: reviewMethodMarkdownForArm(methodArmFromEnv()),
});
