import { defineInstructions } from "@grok/agent-sdk";
import { methodArmFromEnv, reviewMethodMarkdownForArm } from "./lib/method-variants.js";

/** R2 exam arms: set `R2_METHOD_ARM` to `A`|`B`|`C`|`D`|`F` (`F` = unredacted repo reads; instructions stay arm A). Default `A`. Arm `C` is for R2/R4 eval only — do not ship production with inline skills unless explicitly measured. */
export default defineInstructions({
  markdown: reviewMethodMarkdownForArm(methodArmFromEnv()),
});
