/**
 * JUnit XML, taken from the cloud runner's own artifact for an exact SHA.
 *
 * ## Why not from the caller
 *
 * `compare_suite_runs` used to accept `baseJunit` / `headJunit` as text. An
 * empty or truncated string parses to zero failures, so whoever called the tool
 * decided the result of the suite gate. The XML now comes from GitHub Actions'
 * artifacts for the SHA being gated, and a head with no artifact is a refusal,
 * not a pass.
 *
 * ## The zip, without a dependency
 *
 * An Actions artifact is a zip. Node has `zlib.inflateRawSync`, which is the
 * only thing a deflate zip actually needs beyond a directory walk, so the
 * reader here is central-directory + local header + inflate. It handles the two
 * methods GitHub emits (stored and deflate) and refuses anything else rather
 * than guessing.
 */

import { inflateRawSync } from "node:zlib";
import type { Octokit } from "@octokit/rest";
import { assertWellFormed } from "./xml.js";

export const SUITE_WORKFLOW = "ci-smoke.yml";
export const JUNIT_ARTIFACT = "pytest-junit";

export type ZipEntry = { name: string; data: Uint8Array };

/** The most one report may inflate to. The head's artifact is written by the PR's own code. */
export const MAX_ENTRY_BYTES = 64 * 1024 * 1024;

const EOCD = 0x06054b50;
const CENTRAL = 0x02014b50;
const LOCAL = 0x04034b50;

/**
 * Every file in a zip archive. Throws on a truncated or multi-disk archive so a
 * partial read can never masquerade as a complete one.
 */
export function readZip(bytes: Uint8Array): ZipEntry[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  let eocd = -1;
  for (let i = bytes.length - 22; i >= 0 && i >= bytes.length - 22 - 0xffff; i -= 1) {
    if (view.getUint32(i, true) === EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd === -1) {
    throw new Error("zip: end of central directory not found (truncated archive)");
  }

  const count = view.getUint16(eocd + 10, true);
  const directorySize = view.getUint32(eocd + 12, true);
  const directoryOffset = view.getUint32(eocd + 16, true);
  if (directoryOffset + directorySize > bytes.length) {
    throw new Error("zip: central directory runs past the end of the archive");
  }

  const entries: ZipEntry[] = [];
  let cursor = directoryOffset;
  for (let index = 0; index < count; index += 1) {
    if (view.getUint32(cursor, true) !== CENTRAL) {
      throw new Error(`zip: bad central directory header at entry ${index}`);
    }
    const method = view.getUint16(cursor + 10, true);
    const compressedSize = view.getUint32(cursor + 20, true);
    const declaredSize = view.getUint32(cursor + 24, true);
    const nameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    const localOffset = view.getUint32(cursor + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength));

    if (!name.endsWith("/")) {
      if (declaredSize > MAX_ENTRY_BYTES) {
        throw new Error(`zip: ${name} is too large (${declaredSize} bytes declared, limit ${MAX_ENTRY_BYTES})`);
      }
      if (view.getUint32(localOffset, true) !== LOCAL) {
        throw new Error(`zip: bad local header for ${name}`);
      }
      const localNameLength = view.getUint16(localOffset + 26, true);
      const localExtraLength = view.getUint16(localOffset + 28, true);
      const start = localOffset + 30 + localNameLength + localExtraLength;
      const raw = bytes.subarray(start, start + compressedSize);
      if (method === 0) {
        entries.push({ name, data: raw });
      } else if (method === 8) {
        // The declared size is only a claim; the limit is enforced while inflating.
        entries.push({ name, data: new Uint8Array(inflateRawSync(raw, { maxOutputLength: MAX_ENTRY_BYTES })) });
      } else {
        throw new Error(`zip: ${name} uses unsupported compression method ${method}`);
      }
    }

    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

/**
 * Concatenate every JUnit report in the archive into one document.
 *
 * A pytest run with `--junitxml` writes a single file, but `pytest-xdist` and a
 * sharded job both write several. Every `<testcase>` in the archive belongs to
 * the same SHA, so folding the roots into one `<testsuites>` keeps the diff
 * correct either way.
 */
export function junitFromEntries(entries: readonly ZipEntry[]): string {
  const reports = entries.filter((entry) => /(^|\/)(?:junit[^/]*|pytest|report)\.xml$/i.test(entry.name));
  if (reports.length === 0) {
    throw new Error(
      `artifact has no JUnit report (looked for junit*.xml / pytest.xml / report.xml, saw ${entries.map((e) => e.name).join(", ") || "nothing"})`,
    );
  }
  const parts = reports.map((report) => {
    const text = new TextDecoder().decode(report.data);
    // Each shard on its own: re-rooting strips the outer tags, which would
    // quietly repair a shard cut off before its closing `</testsuites>`.
    try {
      assertWellFormed(text);
    } catch (error) {
      throw new Error(`${report.name}: ${error instanceof Error ? error.message : String(error)}`);
    }
    return text;
  });
  return `<?xml version="1.0"?><testsuites>${parts
    .map((part) => part.replace(/^<\?xml[^>]*\?>/, "").replace(/<\/?testsuites\b[^>]*>/g, ""))
    .join("")}</testsuites>`;
}

export type ArtifactRef = { id: number; name: string };

/**
 * The artifact to read: the one this workflow uploaded, newest first.
 *
 * Named rather than positional on purpose. Picking "the only artifact" would
 * silently read a coverage report as the suite result the day a second upload
 * appears.
 */
export function pickArtifact(artifacts: readonly ArtifactRef[]): ArtifactRef | undefined {
  return artifacts.find((artifact) => artifact.name === JUNIT_ARTIFACT);
}

/** Conclusions that mean the suite job ran to its end, whether it passed or not. */
const FINISHED = new Set(["success", "failure", "neutral"]);

/**
 * The workflow run to read for one SHA: the newest run that finished.
 *
 * A cancelled or timed-out run stopped partway, so its report is a fragment of
 * the suite and must not stand in for the whole one.
 */
export function pickRun(runs: readonly { id: number; conclusion: string | null }[]): { id: number } | undefined {
  return runs.find((run) => run.conclusion !== null && FINISHED.has(run.conclusion));
}

export type JunitFetch =
  | { ok: true; xml: string; runId: number; artifact: string }
  | { ok: false; reason: "no-run" | "no-artifact" | "unreadable"; detail: string };

export type RunnerReader = {
  /** Workflow runs of the suite workflow for one head SHA. */
  runsForSha(sha: string): Promise<{ id: number; conclusion: string | null }[]>;
  artifactsForRun(runId: number): Promise<ArtifactRef[]>;
  /** Raw zip bytes of one artifact. */
  artifactZip(artifactId: number): Promise<Uint8Array>;
};

/**
 * The bytes of a downloaded artifact.
 *
 * `downloadArtifact` types its payload as `unknown` and, for a zip, resolves an
 * `ArrayBuffer`. A cast to `Uint8Array` compiles and then fails inside the
 * reader, which reported every real artifact as unreadable.
 */
export function artifactBytes(data: unknown): Uint8Array {
  if (data instanceof Uint8Array) {
    return data;
  }
  if (data instanceof ArrayBuffer) {
    return new Uint8Array(data);
  }
  throw new Error(`artifact download was ${data === null ? "null" : typeof data}, not binary`);
}

/** The reader backed by the real GitHub API. */
export function octokitRunner(octokit: Octokit, ref: { owner: string; repo: string }): RunnerReader {
  return {
    async runsForSha(sha) {
      const { data } = await octokit.rest.actions.listWorkflowRuns({
        owner: ref.owner,
        repo: ref.repo,
        workflow_id: SUITE_WORKFLOW,
        head_sha: sha,
        per_page: 20,
      });
      return data.workflow_runs.map((run) => ({ id: run.id, conclusion: run.conclusion ?? null }));
    },
    async artifactsForRun(runId) {
      const { data } = await octokit.rest.actions.listWorkflowRunArtifacts({
        owner: ref.owner,
        repo: ref.repo,
        run_id: runId,
        per_page: 100,
      });
      return data.artifacts.map((artifact) => ({ id: artifact.id, name: artifact.name }));
    },
    async artifactZip(artifactId) {
      const { data } = await octokit.rest.actions.downloadArtifact({
        owner: ref.owner,
        repo: ref.repo,
        artifact_id: artifactId,
        archive_format: "zip",
      });
      return artifactBytes(data);
    },
  };
}

/**
 * JUnit XML for one SHA, or a refusal.
 *
 * Every failure is a refusal and none of them is an empty report: "no run yet"
 * and "the artifact expired" must never be read as "no failures", which is what
 * happened when the XML came in as a tool argument.
 */
export async function fetchJunit(reader: RunnerReader, sha: string): Promise<JunitFetch> {
  const run = pickRun(await reader.runsForSha(sha));
  if (run === undefined) {
    return { ok: false, reason: "no-run", detail: `no completed ${SUITE_WORKFLOW} run for ${sha}` };
  }
  const artifact = pickArtifact(await reader.artifactsForRun(run.id));
  if (artifact === undefined) {
    return {
      ok: false,
      reason: "no-artifact",
      detail: `run ${run.id} for ${sha} has no "${JUNIT_ARTIFACT}" artifact (expired, or the job did not reach the upload)`,
    };
  }
  try {
    const zip = await reader.artifactZip(artifact.id);
    return { ok: true, xml: junitFromEntries(readZip(zip)), runId: run.id, artifact: artifact.name };
  } catch (error) {
    return {
      ok: false,
      reason: "unreadable",
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}
