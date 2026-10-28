/**
 * Per-case and per-run report for the hard exam, read from `agent-sdk eval --json` output.
 *
 *   npx tsx evals/report-hard.ts reports/hard.json
 *
 * It does not trust the runner's own `ok`: a run passes only when every `det:` assertion passed AND the judge ran
 * and cleared its bar. A judge assertion in a run whose deterministic checks failed is reported as a violation
 * (the eval never calls the judge then), and the run is still a failure. A case passes only when all of its
 * iterations pass.
 */
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export type Assertion = { name: string; passed: boolean; score?: number; threshold?: number };
export type RunResult = { id: string; ok?: boolean; assertions: Assertion[]; metrics?: Record<string, string | number>; error?: string };

export type RunReport = {
  id: string;
  iteration: string;
  detPassed: number;
  detTotal: number;
  failedChecks: string[];
  judge: "passed" | "failed" | "not-run";
  grade: "pass" | "fail";
  notes: string[];
};
export type CaseReport = { caseId: string; runs: RunReport[]; passed: number; total: number; grade: "pass" | "fail" };

const isDet = (a: Assertion): boolean => a.name.startsWith("det: ");
const isJudge = (a: Assertion): boolean => !isDet(a) && (a.score !== undefined || a.threshold !== undefined);

export function parseId(id: string): { caseId: string; iteration: string } {
  const parts = id.split("/");
  const iteration = /^\d+$/.test(parts[parts.length - 1] ?? "") ? parts.pop()! : "1";
  return { caseId: parts[parts.length - 1] ?? id, iteration };
}

export function gradeRun(result: RunResult): RunReport {
  const { caseId, iteration } = parseId(result.id);
  const det = result.assertions.filter(isDet);
  const judges = result.assertions.filter(isJudge);
  const failedChecks = det.filter((a) => !a.passed).map((a) => a.name.slice("det: ".length));
  const notes: string[] = [];
  const judge: RunReport["judge"] = judges.length === 0 ? "not-run" : judges.every((a) => a.passed) ? "passed" : "failed";
  if (failedChecks.length > 0 && judges.length > 0) {
    notes.push("judge ran after a failed deterministic check (it cannot rescue the run)");
  }
  if (result.error !== undefined) {
    notes.push(`error: ${result.error.slice(0, 120)}`);
  }
  const bad = result.assertions.filter((a) => !isDet(a) && !isJudge(a) && !a.passed).map((a) => a.name);
  if (bad.length > 0) {
    notes.push(`runtime assertions failed: ${bad.join(", ")}`);
  }
  const grade = det.length > 0 && failedChecks.length === 0 && judge === "passed" && bad.length === 0 && result.error === undefined ? "pass" : "fail";
  if (result.ok === true && grade === "fail") {
    notes.push("runner said ok, recomputed grade is fail");
  }
  return { id: caseId, iteration, detPassed: det.length - failedChecks.length, detTotal: det.length, failedChecks, judge, grade, notes };
}

export function summarize(results: readonly RunResult[]): CaseReport[] {
  const byCase = new Map<string, RunReport[]>();
  for (const r of results) {
    const run = gradeRun(r);
    byCase.set(run.id, [...(byCase.get(run.id) ?? []), run]);
  }
  return [...byCase.entries()].map(([caseId, runs]) => ({
    caseId,
    runs: runs.sort((a, b) => Number(a.iteration) - Number(b.iteration)),
    passed: runs.filter((r) => r.grade === "pass").length,
    total: runs.length,
    grade: runs.every((r) => r.grade === "pass") ? "pass" : "fail",
  }));
}

export function render(cases: readonly CaseReport[]): string {
  const lines: string[] = [];
  for (const c of cases) {
    lines.push(`${c.grade === "pass" ? "PASS" : "FAIL"}  ${c.caseId}  ${c.passed}/${c.total} runs`);
    for (const r of c.runs) {
      lines.push(`      run ${r.iteration}: ${r.grade}  det ${r.detPassed}/${r.detTotal}  judge ${r.judge}`);
      for (const f of r.failedChecks) {
        lines.push(`        failed check: ${f}`);
      }
      for (const n of r.notes) {
        lines.push(`        note: ${n}`);
      }
    }
  }
  const passed = cases.filter((c) => c.grade === "pass").length;
  lines.push("", `${passed}/${cases.length} cases pass (a case needs every run to pass)`);
  return lines.join("\n");
}

export function load(text: string): RunResult[] {
  const data = JSON.parse(text) as unknown;
  const list = Array.isArray(data) ? data : ((data as { results?: unknown }).results as unknown[] | undefined);
  if (!Array.isArray(list)) {
    throw new Error("expected an array of results or an object with `results`");
  }
  return list as RunResult[];
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const file = process.argv[2];
  if (file === undefined) {
    throw new Error("usage: tsx evals/report-hard.ts <eval --json output>");
  }
  const cases = summarize(load(readFileSync(file, "utf8")));
  console.log(render(cases));
  process.exitCode = cases.every((c) => c.grade === "pass") ? 0 : 1;
}
