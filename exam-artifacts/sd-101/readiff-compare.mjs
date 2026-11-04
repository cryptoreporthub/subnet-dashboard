#!/usr/bin/env node
/**
 * SD-101 byte-identity harness: production readDiff on three mocked compares.
 * Run from review-gate-bot/ (see ../exam-artifacts/sd-101/README.md).
 */
import { readDiff } from "./bot/lib/repo.js";

const REF = { owner: "o", repo: "r", number: 7 };
const HEAD = "a".repeat(40);
const BASE = "b".repeat(40);

/** @param {readonly import("./bot/lib/repo.js").DiffCompareFile[]} files */
function compareOctokit(files) {
  return {
    rest: {
      repos: {
        compareCommitsWithBasehead: async () => ({ data: { files } }),
      },
    },
  };
}

function bearerLineFiles() {
  const bearerVal = "supersecretbearer1234567890";
  const secretVal = "clientsecretvalue1234567890";
  const patch = `+def _bearer_ok(bearer=${bearerVal} | None) -> bool:\n+DEFAULT_CLIENT_SECRET=${secretVal}\n`;
  return [{ filename: "internal/auth.py", status: "modified", additions: 2, deletions: 0, patch }];
}

function overBudgetFiles() {
  const big = "+" + "x".repeat(70_000);
  return [
    { filename: "one.py", status: "modified", additions: 1, deletions: 0, patch: big },
    { filename: "two.py", status: "modified", additions: 1, deletions: 0, patch: big },
    { filename: "three.py", status: "modified", additions: 1, deletions: 0, patch: big },
  ];
}

function renameFiles() {
  return [
    {
      filename: "docs/new.md",
      previous_filename: "docs/old.md",
      status: "renamed",
      additions: 1,
      deletions: 0,
      patch: "+x\n",
    },
  ];
}

/** @param {string} name @param {ReturnType<typeof bearerLineFiles>} files */
async function runCase(name, files) {
  const out = await readDiff(compareOctokit(files), REF, { head: HEAD, base: BASE });
  if (!out.ok) {
    throw new Error(`${name}: ${out.reason} — ${out.detail ?? ""}`);
  }
  return out;
}

const result = {
  "bearer-line": await runCase("bearer-line", bearerLineFiles()),
  "over-budget": await runCase("over-budget", overBudgetFiles()),
  rename: await runCase("rename", renameFiles()),
};

process.stdout.write(`${JSON.stringify(result)}\n`);
