import { defineInstructions } from "@grok/agent-sdk";
import { methodArmFromEnv, reviewMethodMarkdownForArm } from "./lib/method-variants.js";

/** R2 arms: set `R2_METHOD_ARM` to `A`|`B`|`C`|`D` (default `C`). */
export default defineInstructions({
  markdown: reviewMethodMarkdownForArm(methodArmFromEnv()),
});
