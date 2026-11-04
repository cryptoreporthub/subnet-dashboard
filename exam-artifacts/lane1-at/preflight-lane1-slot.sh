#!/usr/bin/env bash
# V1 preflight: strict sysprompt for fresh-A base bot; log-only for arm-G candidate bot.
set -euo pipefail
cd "$(dirname "$0")/../../review-gate-bot"
ARM="${R2_METHOD_ARM:-A}"
ROLE="${LANE1_ROLE:-freshA}"
node --input-type=module <<EOF
import { createHash } from "node:crypto";
import { loadAgentProject } from "@grok/agent-sdk";

const EXPECTED_A = { chars: 6874, sha: "46c634666738fa8f6eb61cb1e79d4dee5fb207d531a012513516601705e05feb" };
const arm = process.env.R2_METHOD_ARM ?? "A";
const role = process.env.LANE1_ROLE ?? "freshA";
process.env.R2_METHOD_ARM = arm;
const { agent } = await loadAgentProject(".");
const text = agent.instructions;
if (typeof text !== "string") {
  console.error("STOP: instructions not a string");
  process.exit(2);
}
const sha = createHash("sha256").update(text).digest("hex");
const modelJson = JSON.stringify(agent.model);
const expectedModel = JSON.stringify({ id: "composer-2.5", params: [{ id: "fast", value: "false" }] });
console.log(\`sysprompt_chars=\${text.length}\`);
console.log(\`sysprompt_sha256=\${sha}\`);
console.log(\`model_object=\${modelJson}\`);
console.log(\`lane1_role=\${role}\`);
if (modelJson !== expectedModel) {
  console.error("STOP V1: model mismatch");
  process.exit(4);
}
if (role === "freshA" && arm === "A") {
  if (text.length !== EXPECTED_A.chars || sha !== EXPECTED_A.sha) {
    console.error(\`STOP V1: fresh-A sysprompt mismatch got \${text.length}/\${sha}\`);
    process.exit(3);
  }
} else {
  console.log("sysprompt_check=logged_not_enforced");
}
console.log("preflight_ok");
EOF
