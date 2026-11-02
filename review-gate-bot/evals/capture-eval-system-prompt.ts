import { loadAgentProject } from "@grok/agent-sdk";

/** Same bytes the eval runner mounts as the agent system prompt (bot @ cwd). */
export async function capture_eval_system_prompt(projectRoot: string): Promise<string> {
  const { project } = await loadAgentProject(projectRoot);
  const instructions = project.agent.instructions;
  if (instructions === undefined || instructions === "") {
    throw new Error("capture_eval_system_prompt: agent instructions empty");
  }
  return instructions;
}
