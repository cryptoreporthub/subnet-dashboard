import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import { observePair } from "../bot/lib/pair-observation.js";

const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const HEAD = "a".repeat(40);
const TIP = "b".repeat(40);
const MERGE = "c".repeat(40);
const baseRepo = { owner: { login: REF.owner }, name: REF.repo };

function octokitForCompare(mergeBaseCommit: { sha: string } | null): Octokit {
  return {
    rest: {
      pulls: {
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: HEAD },
            base: { sha: MERGE, ref: "main", repo: baseRepo },
            draft: false,
          },
        }),
      },
      repos: {
        getBranch: async () => ({ data: { commit: { sha: TIP } } }),
        compareCommitsWithBasehead: async () => ({
          data: {
            merge_base_commit: mergeBaseCommit,
            files: [],
          },
        }),
      },
    },
  } as unknown as Octokit;
}

test("M3: null merge_base_commit is BaseUnavailable", async () => {
  const obs = await observePair(octokitForCompare(null), REF);
  assert.equal(obs.kind, "base-unavailable");
});

test("M3: present but empty merge_base sha is PairReadFailed(compare)", async () => {
  const obs = await observePair(octokitForCompare({ sha: "" }), REF);
  assert.equal(obs.kind, "pair-read-failed");
  if (obs.kind === "pair-read-failed") {
    assert.equal(obs.stage, "compare");
    assert.equal(obs.code, "invalid-merge-base-sha");
  }
});
