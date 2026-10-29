/**
 * Re-grade saved hard-exam artifact JSON (no model).
 *   PACK_DIR=.../1522-evals-hard-results-r7/runs npx tsx evals/regrade-saved.ts
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { allPass, evaluate, type CaseSpec, type Facts, type ToolCallFact } from "./hard-grading.js";

const packDir = process.env.PACK_DIR ?? "";
if (packDir === "") {
  throw new Error("set PACK_DIR to the saved r7 runs directory");
}

type Artifact = {
  id?: string;
  finalText?: string;
  toolCalls?: { toolName: string; args?: unknown; input?: unknown; output?: unknown; isError?: boolean }[];
  inputs?: string[];
};

function mapCalls(raw: Artifact["toolCalls"]): ToolCallFact[] {
  return (raw ?? []).map((c) => ({
    toolName: c.toolName,
    input: c.input ?? c.args,
    output: c.output,
    status: c.isError ? "failed" : undefined,
  }));
}

function parseId(id: string): { caseId: string; iteration: string } {
  const parts = id.split("/");
  const iteration = /^\d+$/.test(parts[parts.length - 1] ?? "") ? parts.pop()! : "1";
  return { caseId: parts[parts.length - 1] ?? id, iteration };
}

function ctxFromInputs(inputs: string[] | undefined): { headSha: string; number: number } {
  const text = inputs?.[0] ?? "";
  const head = text.match(/head ([0-9a-f]{40})/i)?.[1] ?? text.match(/\bto ([0-9a-f]{40})/i)?.[1] ?? "0".repeat(40);
  const num = Number(text.match(/PR (\d+)/)?.[1] ?? 9000);
  return { headSha: head, number: num };
}

function findArtifacts(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name.endsWith(".artifacts")) {
        const evalRoot = join(path, "evals", "review-gate-hard");
        try {
          for (const caseDir of readdirSync(evalRoot)) {
            for (const file of readdirSync(join(evalRoot, caseDir))) {
              if (file.endsWith(".json")) {
                out.push(join(evalRoot, caseDir, file));
              }
            }
          }
        } catch {
          /* no artifacts tree */
        }
      }
      continue;
    }
  }
  return out;
}

async function main(): Promise<void> {
  const mod: { SPECS: CaseSpec[] } = await import(process.env.OLD_SPECS === "1" ? "./hard-specs.js" : "./hard-specs-clause-aware.js");
  const { SPECS } = mod;
  const byCase = new Map<string, { oldDetFail: number; newDetFail: number; runs: number; fixed: string[] }>();

  for (const path of findArtifacts(packDir)) {
    const art = JSON.parse(readFileSync(path, "utf8")) as Artifact;
    if (art.id === undefined || art.finalText === undefined) {
      continue;
    }
    const { caseId, iteration } = parseId(art.id);
    const spec = SPECS.find((s) => s.id === caseId);
    if (spec === undefined) {
      continue;
    }
    const ctx = ctxFromInputs(art.inputs);
    const facts: Facts = { toolCalls: mapCalls(art.toolCalls), reply: art.finalText };
    const checks = evaluate(spec, facts, ctx);
    const newFail = checks.filter((c) => !c.pass).map((c) => c.name);

    const summaryPath = join(packDir, `${caseId}-${iteration}.summary.json`);
    let oldFailed: string[] = [];
    try {
      const s = JSON.parse(readFileSync(summaryPath, "utf8")) as { failedDet?: string[]; status?: string };
      oldFailed = s.failedDet ?? [];
    } catch {
      /* no summary */
    }

    const bucket = byCase.get(caseId) ?? { oldDetFail: 0, newDetFail: 0, runs: 0, fixed: [] };
    bucket.runs += 1;
    if (oldFailed.length > 0) bucket.oldDetFail += 1;
    if (newFail.length > 0) bucket.newDetFail += 1;
    if (oldFailed.length > 0 && newFail.length === 0) {
      bucket.fixed.push(`${caseId}/${iteration}: was ${oldFailed.join(",")}`);
    }
    byCase.set(caseId, bucket);

    console.log(`${caseId}/${iteration}\toldDetFail=${oldFailed.length > 0}\tnewDetFail=${newFail.length > 0}\t${newFail.join(";")}`);
  }

  let oldRuns = 0;
  let newRuns = 0;
  console.log("\n=== r7 det-fail run counts (old from summary.failedDet) ===");
  for (const [caseId, b] of [...byCase.entries()].sort()) {
    oldRuns += b.oldDetFail;
    newRuns += b.newDetFail;
    console.log(`${caseId}\truns=${b.runs}\toldDetFailRuns=${b.oldDetFail}\tnewDetFailRuns=${b.newDetFail}`);
    for (const f of b.fixed) {
      console.log(`  fixed: ${f}`);
    }
  }
  console.log(`\nTOTAL det-fail runs: old ${oldRuns} → new ${newRuns} (artifacts in ${packDir})`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
