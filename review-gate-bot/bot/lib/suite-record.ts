import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { prKey } from "./gate.js";
import { readSuiteRecord, legacySuiteKey, suiteKey, readLivePair, pairCompareReady, type PrRef } from "./gh.js";
import { knownFlakes } from "./flakes.js";
import { exclusive } from "./lock.js";
import { fetchJunit, octokitRunner, pickRun, type RunnerReader } from "./runner.js";
import { diffJunit, suiteDefinitionFiles, type SuiteDiff } from "./suite.js";
import { DIFF_FILE_CAP } from "./repo.js";

/**
 * A list of names for a detail string: the count, the first few, and how many more. The full list is kept in the
 * record by the caller. Each name is cut, so a long test name cannot push the check summary past GitHub's size limit.
 */
function listed(label: string, names: readonly string[]): string {
  const shown = names.slice(0, 5).map((name) => (name.length > 120 ? `${name.slice(0, 120)}…` : name));
  const more = names.length - shown.length;
  return `${label}: ${names.length} (${shown.join(", ")}${more > 0 ? `, and ${more} more` : ""})`;
}

/**
 * What the compare says about the suite's definition. A list at GitHub's cap is cut short, so a suite-definition
 * change could be among the files left out: that is unknown, not empty, and it is refused. The cap is on
 * `files` alone. More than 250 commits trims `commits`, and the file list still covers the whole comparison.
 */
export type DefinitionRead = { complete: true; files: string[] } | { complete: false; detail: string };

async function readDefinition(input: { octokit: Octokit; ref: PrRef; headSha: string; baseSha: string }): Promise<DefinitionRead> {
  const { data } = await input.octokit.rest.repos.compareCommitsWithBasehead({
    owner: input.ref.owner,
    repo: input.ref.repo,
    basehead: `${input.baseSha}...${input.headSha}`,
  });
  // No list at all is not a fact about this PR. It fails the delivery, so nothing is recorded and the next one asks again.
  if (data.files === undefined) {
    throw new Error("the compare returned no file list");
  }
  if (data.files.length >= DIFF_FILE_CAP) {
    return { complete: false, detail: `the PR changes ${DIFF_FILE_CAP} or more files, so its suite definition cannot be read whole` };
  }
  // A rename counts both paths.
  const changed = data.files.flatMap((file) =>
    file.previous_filename === undefined ? [file.filename] : [file.filename, file.previous_filename],
  );
  return { complete: true, files: suiteDefinitionFiles(changed) };
}

/**
 * Record a head as NEEDS-JOSHUA: final, with the reason. No run is looked up for it again. A changed suite
 * definition passes the files that did it: the detail names the first few, and the record keeps every path.
 * That list is bounded by the compare itself, since a compare at the file cap is refused before any path is read.
 */
async function recordRefusal(
  input: { kv: HostKvApi; ref: PrRef; headSha: string },
  refusal: { reason: string; detail: string; files?: string[] },
): Promise<string> {
  console.warn(JSON.stringify({ level: "warn", event: "needs_joshua", reason: refusal.reason, pr: prKey(input.ref), head: input.headSha, files: refusal.files ?? [] }));
  await input.kv.put(legacySuiteKey(input.ref, input.headSha), {
    state: "regressed",
    invalid: "needs-joshua",
    detail: refusal.detail,
    ...(refusal.files === undefined ? {} : { definitionFiles: refusal.files }),
    newFailures: [],
    at: Date.now(),
  });
  return refusal.detail;
}

/** Refuse a head whose compare cannot be read whole, or whose PR changes the suite's definition. Undefined when it may go on. */
async function refuseUnlessDefinitionClear(
  input: { kv: HostKvApi; ref: PrRef; headSha: string },
  definition: DefinitionRead,
): Promise<{ reason: "diff-incomplete" | "suite-definition-changed"; detail: string } | undefined> {
  if (!definition.complete) {
    const detail = await recordRefusal(input, { reason: "diff-incomplete", detail: definition.detail });
    return { reason: "diff-incomplete", detail };
  }
  if (definition.files.length > 0) {
    const detail = await recordRefusal(input, {
      reason: "suite-definition-changed",
      detail: listed("suite definition changed", definition.files),
      files: definition.files,
    });
    return { reason: "suite-definition-changed", detail };
  }
  return undefined;
}

export type SuiteComparison =
  | { ok: true; diff: SuiteDiff; headRunId: number; baseRunId: number; flakeList: string }
  | { ok: false; step: "head" | "base"; reason: string; detail: string };

export type ComparisonInput = {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  /** Merge-base JUnit compare target. */
  baseSha: string;
  /** Live base-branch tip for the pair key. */
  baseTipSha: string;
  reader?: RunnerReader;
};

function unavailableBase(): SuiteComparison {
  return { ok: false, step: "base", reason: "base-unavailable", detail: "merge-base or base tip is not available" };
}

/**
 * Compare the full suite at `baseSha` and `headSha` from their JUnit artifacts, and record the head's
 * result. Shared by the `compare_suite_runs` tool and the gate's own driver, so both record the same
 * thing. A missing artifact is a wait and records nothing, so it is never a regressed result. A guard hit
 * (NEEDS-JOSHUA) records the head as regressed with its reason and files, so the block is visible.
 *
 * It always reads the compare itself. A caller cannot hand it a definition read, so no caller can skip
 * the suite-definition check with an empty, stale or other-head value.
 */
export async function recordSuiteComparison(input: ComparisonInput): Promise<SuiteComparison> {
  if (!pairCompareReady(input)) {
    return unavailableBase();
  }
  let definition: DefinitionRead;
  try {
    definition = await readDefinition(input);
  } catch {
    return { ok: false, step: "head", reason: "compare-unavailable", detail: "the PR file compare could not be read" };
  }
  const refusal = await refuseUnlessDefinitionClear(input, definition);
  if (refusal !== undefined) {
    return { ok: false, step: "head", reason: "needs-joshua", detail: refusal.detail };
  }
  return recordComparison(input);
}

/**
 * The comparison itself, with no definition check. Private: the only caller besides `recordSuiteComparison`
 * is `runSuiteIfDue`, which has just checked the definition from the compare it read for this same head.
 */
async function recordComparison(input: ComparisonInput): Promise<SuiteComparison> {
  if (!pairCompareReady(input)) {
    return unavailableBase();
  }
  const reader = input.reader ?? octokitRunner(input.octokit, { owner: input.ref.owner, repo: input.ref.repo });
  const headSha = input.headSha;
  const baseTipSha = input.baseTipSha;
  const baseSha = input.baseSha;
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
  const detail =
    diff.invalid === "baseline-test-missing"
      ? listed("missing at head", diff.missing)
      : diff.invalid === "newly-skipped"
        ? listed("newly skipped at head", diff.skipped)
        : undefined;
  const live = await readLivePair(input.octokit, input.ref);
  if (live.headSha !== headSha || live.baseTipSha !== baseTipSha || live.baseSha !== baseSha) {
    return { ok: false, step: "head", reason: "stale-pair", detail: "head, merge-base, or base tip moved before the suite record was written" };
  }
  await input.kv.put(
    suiteKey(input.ref, input.headSha, baseTipSha),
    {
      state: diff.clean && diff.invalid === undefined ? "clean" : "regressed",
      newFailures: diff.newFailures,
      runId: head.runId,
      invalid: diff.invalid ?? null,
      missing: diff.missing,
      skipped: diff.skipped,
      ...(detail === undefined ? {} : { detail }),
      at: Date.now(),
    },
  );
  return { ok: true, diff, headRunId: head.runId, baseRunId: base.runId, flakeList: flakes.source };
}

/** A head whose newest run's artifact could not be read, remembered so the next delivery does not download it again. */
function refusalKey(ref: PrRef, headSha: string): string {
  return `suite-refusal:${prKey(ref)}:${headSha}`;
}

/**
 * The gate's own suite step: record the full-suite comparison for this head when the gate needs it,
 * and do nothing otherwise. Returns a label for the audit line.
 */
export async function runSuiteIfDue(input: {
  octokit: Octokit;
  kv: HostKvApi;
  ref: PrRef;
  headSha: string;
  baseSha: string;
  baseTipSha: string;
  reader?: RunnerReader;
}): Promise<string> {
  if (!pairCompareReady(input)) {
    return "refused:base-unavailable";
  }
  const reader = input.reader ?? octokitRunner(input.octokit, { owner: input.ref.owner, repo: input.ref.repo });
  const baseTipSha = input.baseTipSha;
  return exclusive(`suite-run:${prKey(input.ref)}:${input.headSha}`, async () => {
    if ((await readSuiteRecord(input.kv, input.ref, input.headSha, baseTipSha))?.invalid === "needs-joshua") {
      return "already-refused";
    }
    let definition: DefinitionRead;
    try {
      definition = await readDefinition(input);
    } catch {
      return "refused:head-compare-unavailable";
    }
    const refusal = await refuseUnlessDefinitionClear(input, definition);
    if (refusal !== undefined) {
      return refusal.reason === "diff-incomplete" ? "refused:head-diff-incomplete" : "refused:head-needs-joshua";
    }
    const latest = pickRun(await reader.runsForSha(input.headSha));
    if (latest === undefined) {
      return "waiting:no-run";
    }
    const recorded = await readSuiteRecord(input.kv, input.ref, input.headSha, baseTipSha);
    if (recorded !== undefined && recorded.runId === latest.id && recorded.state !== "carried") {
      return "already-recorded";
    }
    const refused = (await input.kv.get(refusalKey(input.ref, input.headSha))) as { runId?: number } | undefined;
    if (refused?.runId === latest.id) {
      return "already-refused";
    }
    const outcome = await recordComparison(input);
    if (outcome.ok) {
      return "recorded";
    }
    if (!outcome.ok && outcome.reason === "stale-pair") {
      return "stale-pair";
    }
    if (!outcome.ok && outcome.reason === "base-unavailable") {
      return "refused:base-unavailable";
    }
    // Only a permanent fact about this run is remembered. A lookup or a download that failed on GitHub is transient.
    if (outcome.step === "head" && (outcome.reason === "unreadable" || outcome.reason === "no-artifact")) {
      await input.kv.put(refusalKey(input.ref, input.headSha), { runId: latest.id, reason: outcome.reason });
    }
    return `refused:${outcome.step}-${outcome.reason}`;
  });
}
