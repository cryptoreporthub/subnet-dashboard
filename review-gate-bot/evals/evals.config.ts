import { defineEvalConfig } from "@grok/agent-sdk/evals";
import agent from "../bot/agent.js";

/** Bot under measurement for every eval run (must match `bot/agent.ts`). */
export const evalBotModel = (agent as unknown as { model: { id: string; params: { id: string; value: string }[] } })
  .model;

export default defineEvalConfig({
  maxConcurrency: 6,
  judge: { model: { id: "grok-4.7", params: [{ id: "effort", value: "high" }] } },
});
