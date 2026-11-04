#!/usr/bin/env bash
# V1 preflight for one R2 slot (model + composed instruction hash).
set -euo pipefail
cd "$(dirname "$0")/../../review-gate-bot"
ARM="${R2_METHOD_ARM:-A}"
node --input-type=module <<EOF
import { createHash } from "node:crypto";
import { loadAgentProject } from "@grok/agent-sdk";

const EXPECTED = {
  A: { chars: 6874, sha: "46c634666738fa8f6eb61cb1e79d4dee5fb207d531a012513516601705e05feb" },
  B: { chars: 8292, sha: "4929c7690a09991f4dbc6c9da99d1953b2bd1459f39ac31d66aef99ecf6c25c2" },
  F: { chars: 6874, sha: "46c634666738fa8f6eb61cb1e79d4dee5fb207d531a012513516601705e05feb" },
  R: { chars: 7421, sha: "294b09bd43f2eb0d1680aada31e5397028ef6cd5a662567898b565b2b2054390" },
};
const arm = process.env.R2_METHOD_ARM ?? "A";
const expect = arm === "R" ? EXPECTED.R : arm === "B" ? EXPECTED.B : arm === "F" ? EXPECTED.F : EXPECTED.A;
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
if (text.length !== expect.chars || sha !== expect.sha) {
  console.error(\`STOP V1: sysprompt mismatch arm=\${arm} got \${text.length}/\${sha}\`);
  process.exit(3);
}
if (modelJson !== expectedModel) {
  console.error("STOP V1: model mismatch");
  process.exit(4);
}
console.log("preflight_ok");
EOF
