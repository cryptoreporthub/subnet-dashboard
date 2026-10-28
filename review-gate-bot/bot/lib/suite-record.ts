import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { prKey } from "./gate.js";
import { readSuiteRecord, suiteKey, type PrRef } from "./gh.js";
import { knownFlakes } from "./flakes.js";
import { exclusive } from "./lock.js";
import { fetchJunit, octokitRunner, pickRun, type RunnerReader } from "./runner.js";
import { diffJunit, suiteDefinitionFiles, type SuiteDiff } from "./suite.js";
import { DIFF_FILE_CAP } from "./repo.js";

export type SuiteComparison =
  | { ok: true; diff: SuiteDiff; headRunId: number; baseRunId: number; flakeList: string }
  | { ok: false; step: "head" | "base"; reason: string; detail: string };

/**
 * Compare the full suite at `baseSha` and `headSha` from their JUnit artifacts, and record the head's
 * result. Shared by the `compare_suite_runs` tool and the gate's own driver, so both record the same
 * thing. Nothing is recorded on a refusal: a missing artifact is a wait, never a regressed result.
 */
export async function recordSuiteComparison(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  baseSha: string;
  reader?: RunnerReader;
}): Promise<SuiteComparison> {
  // The suite's definition comes from the PR. A change to it means the report can no longer be trusted
  // as this suite's, so nothing is read or recorded. A compare too large to read whole is refused too.
  const { data } = await input.octokit.rest.repos.compareCommitsWithBasehead({
    owner: input.ref.owner,
    repo: input.ref.repo,
    basehead: `${input.baseSha}...${input.headSha}`,
  });
  // A rename lists the new path and the old one. The old path is the one the PR stops being: both count.
  const changed = (data.files ?? []).flatMap((file) =>
    file.previous_filename === undefined ? [file.filename] : [file.filename, file.previous_filename],
  );
  if ((data.files ?? []).length >= DIFF_FILE_CAP) {
    return { ok: false, step: "head", reason: "diff-incomplete", detail: `the PR changes ${DIFF_FILE_CAP} or more files, so its suite definition cannot be read whole` };
  }
  const definition = suiteDefinitionFiles(changed);
  if (definition.length > 0) {
    console.warn(JSON.stringify({ level: "warn", event: "needs_joshua", reason: "suite-definition-changed", pr: prKey(input.ref), head: input.headSha, files: definition }));
    // Persisted, so the head's record says why it is blocked and which files did it. Not clean, and not a wait.
    await input.kv.put(suiteKey(input.ref, input.headSha), {
      state: "regressed",
      invalid: "needs-joshua",
      detail: definition.join(", "),
      newFailures: [],
      at: Date.now(),
    });
    return { ok: false, step: "head", reason: "needs-joshua", detail: definition.join(", ") };
  }

  const reader = input.reader ?? octokitRunner(input.octokit, { owner: input.ref.owner, repo: input.ref.repo });
  const head = await fetchJunit(reader, input.headSha);
  if (!head.ok) {
    return { ok: false, step: "head", reason: head.reason, detail: head.detail };
  }
  const base = await fetchJunit(reader, input.baseSha);
  if (!base.ok) {
    return { ok: false, step: "base", reason: base.reason, detail: base.detail };
  }
  const flakes = knownFlakes();
  const diff = diffJunit({ baseXml: base.xml, headXml: head.xml, knownFlakes: flakes.ids });
  // The record keeps the reason and the test IDs behind it: a missing or newly skipped test is a person's call to clear.
  await input.kv.put(suiteKey(input.ref, input.headSha), {
    state: diff.clean && diff.invalid === undefined ? "clean" : "regressed",
    newFailures: diff.newFailures,
    runId: head.runId,
    invalid: diff.invalid ?? null,
    missing: diff.missing,
    skipped: diff.skipped,
    at: Date.now(),
  });
  return { ok: true, diff, headRunId: head.runId, baseRunId: base.runId, flakeList: flakes.source };
}

/** A head whose newest run's artifact could not be read, remembered so the next delivery does not download it again. */
function refusalKey(ref: PrRef, headSha: string): string {
  return `suite-refusal:${prKey(ref)}:${headSha}`;
}

/**
 * The gate's own suite step: record the full-suite comparison for this head when the gate needs it,
 * and do nothing otherwise. Returns a label for the audit line.
 *
 * - No finished run yet: waiting, nothing recorded.
 * - The newest finished run is already recorded for this head: no download.
 * - The newest run's artifact is unreadable or missing: that run is remembered
 *   under a separate key, so the next delivery skips it. The suite record is untouched.
 *
 * `exclusive` queues deliveries for one head in this process only. Two webhooks in one process
 * download once, because the second reads the record the first wrote. Across processes the record
 * is still checked first, so the cost is at most one repeat download.
 */
export async function runSuiteIfDue(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  baseSha: string;
  reader?: RunnerReader;
}): Promise<string> {
  const reader = input.reader ?? octokitRunner(input.octokit, { owner: input.ref.owner, repo: input.ref.repo });
  return exclusive(`suite-run:${prKey(input.ref)}:${input.headSha}`, async () => {
    const latest = pickRun(await reader.runsForSha(input.headSha));
    if (latest === undefined) {
      return "waiting:no-run";
    }
    const recorded = await readSuiteRecord(input.kv, input.ref, input.headSha);
    if (recorded !== undefined && recorded.runId === latest.id && recorded.state !== "carried") {
      return "already-recorded";
    }
    const refused = (await input.kv.get(refusalKey(input.ref, input.headSha))) as { runId?: number } | undefined;
    if (refused?.runId === latest.id) {
      return "already-refused";
    }
    const outcome = await recordSuiteComparison({ ...input, reader });
    if (outcome.ok) {
      return "recorded";
    }
    // Only a permanent fact about this run is remembered. A lookup or a download that failed on GitHub is transient.
    if (outcome.step === "head" && (outcome.reason === "unreadable" || outcome.reason === "no-artifact")) {
      await input.kv.put(refusalKey(input.ref, input.headSha), { runId: latest.id, reason: outcome.reason });
    }
    return `refused:${outcome.step}-${outcome.reason}`;
  });
}
