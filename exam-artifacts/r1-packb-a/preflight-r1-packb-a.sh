#!/usr/bin/env bash
# Preflight for R1-A pack B run (bot pin 5d884c47).
set -euo pipefail
cd "$(dirname "$0")/../../review-gate-bot"
node --input-type=module <<'EOF'
import { createHash } from "node:crypto";
import { loadAgentProject } from "@grok/agent-sdk";

const EXPECTED_CHARS = 6874;
const EXPECTED_SHA = "46c634666738fa8f6eb61cb1e79d4dee5fb207d531a012513516601705e05feb";
const EXPECTED_MODEL = { id: "composer-2.5", params: [{ id: "fast", value: "false" }] };

process.env.R2_METHOD_ARM = process.env.R2_METHOD_ARM ?? "A";
const { agent } = await loadAgentProject(".");
const text = agent.instructions;
if (typeof text !== "string") {
  console.error("STOP: instructions not a string");
  process.exit(2);
}
const sha = createHash("sha256").update(text).digest("hex");
const modelJson = JSON.stringify(agent.model);
const expectedJson = JSON.stringify(EXPECTED_MODEL);
console.log(`sysprompt_chars=${text.length}`);
console.log(`sysprompt_sha256=${sha}`);
console.log(`model_object=${modelJson}`);
if (text.length !== EXPECTED_CHARS || sha !== EXPECTED_SHA) {
  console.error(`STOP: sysprompt mismatch (got ${text.length} chars, sha ${sha})`);
  process.exit(3);
}
if (modelJson !== expectedJson) {
  console.error(`STOP: model mismatch (got ${modelJson})`);
  process.exit(4);
}
if (sha.length !== 64) {
  console.error("STOP: sysprompt sha empty or invalid");
  process.exit(5);
}
console.log("preflight_ok");
EOF
