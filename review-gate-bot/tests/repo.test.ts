import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import { listRepoFiles, readDiff, readRepoFile, validRepoPath } from "../bot/lib/repo.js";

const REF = { owner: "o", repo: "r", number: 7 };
const HEAD = "a".repeat(40);

type FakeFile = { filename: string; status: string; additions: number; deletions: number; patch?: string; previous_filename?: string };

function fake(options: {
  files?: FakeFile[];
  tree?: { path: string; type: string }[];
  truncatedTree?: boolean;
  content?: unknown;
  contentError?: Error;
}): { octokit: Octokit; calls: { content: Record<string, unknown>[] } } {
  const calls = { content: [] as Record<string, unknown>[] };
  const listFiles = async () => ({ data: options.files ?? [] });
  const octokit = {
    paginate: async (fn: (p: unknown) => Promise<{ data: unknown[] }>, params: unknown) => (await fn(params)).data,
    rest: {
      pulls: { listFiles },
      git: { getTree: async () => ({ data: { tree: options.tree ?? [], truncated: options.truncatedTree ?? false } }) },
      repos: {
        getContent: async (params: Record<string, unknown>) => {
          calls.content.push(params);
          if (options.contentError !== undefined) {
            throw options.contentError;
          }
          return { data: options.content };
        },
      },
    },
  } as unknown as Octokit;
  return { octokit, calls };
}

const b64 = (text: string): string => Buffer.from(text, "utf8").toString("base64");

test("the diff carries each file's path, status, counts and patch", async () => {
  const { octokit } = fake({
    files: [{ filename: "a.py", status: "modified", additions: 2, deletions: 1, patch: "@@ -1 +1,2 @@\n-x\n+y\n+z" }],
  });
  const diff = await readDiff(octokit, REF, {});
  assert.equal(diff.totalFiles, 1);
  assert.deepEqual(diff.files[0], {
    path: "a.py",
    status: "modified",
    additions: 2,
    deletions: 1,
    patch: "@@ -1 +1,2 @@\n-x\n+y\n+z",
  });
  assert.equal(diff.truncated, false);
});

test("a file GitHub gives no patch for says so, instead of looking empty", async () => {
  const { octokit } = fake({ files: [{ filename: "img.png", status: "added", additions: 0, deletions: 0 }] });
  const diff = await readDiff(octokit, REF, {});
  assert.equal(diff.files[0]?.patch, undefined);
  assert.match(String(diff.files[0]?.patchOmitted), /binary|large/i);
});

test("a diff past the size budget is cut and says which files were left out", async () => {
  const big = "+" + "x".repeat(70_000);
  const { octokit } = fake({
    files: [
      { filename: "one.py", status: "modified", additions: 1, deletions: 0, patch: big },
      { filename: "two.py", status: "modified", additions: 1, deletions: 0, patch: big },
      { filename: "three.py", status: "modified", additions: 1, deletions: 0, patch: big },
    ],
  });
  const diff = await readDiff(octokit, REF, {});
  assert.equal(diff.truncated, true);
  assert.ok(diff.omittedPaths.includes("three.py"));
  const chars = diff.files.reduce((n, f) => n + (f.patch?.length ?? 0), 0);
  assert.ok(chars <= 130_000, `patch text ${chars}`);
});

test("asking for named files returns only those", async () => {
  const { octokit } = fake({
    files: [
      { filename: "a.py", status: "modified", additions: 1, deletions: 0, patch: "+a" },
      { filename: "b.py", status: "modified", additions: 1, deletions: 0, patch: "+b" },
    ],
  });
  const diff = await readDiff(octokit, REF, { paths: ["b.py"] });
  assert.deepEqual(diff.files.map((f) => f.path), ["b.py"]);
});

test("a secret-shaped value in a patch is scrubbed before it leaves", async () => {
  const token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0";
  const { octokit } = fake({
    files: [{ filename: "x.env", status: "added", additions: 1, deletions: 0, patch: `+GITHUB_TOKEN=${token}` }],
  });
  const diff = await readDiff(octokit, REF, {});
  assert.ok(!JSON.stringify(diff).includes(token));
});

test("paths that climb out, start at the root or carry control characters are refused", () => {
  for (const bad of ["../etc/passwd", "a/../../b", "/abs/path", "a\\b", "a\0b", "", "x".repeat(400)]) {
    assert.equal(validRepoPath(bad), false, JSON.stringify(bad));
  }
  for (const ok of ["internal/council/resolver.py", "README.md", "tests/test_a.py", ".github/workflows/ci.yml"]) {
    assert.equal(validRepoPath(ok), true, ok);
  }
});

test("a file is read at the commit asked for and decoded", async () => {
  const { octokit, calls } = fake({
    content: { type: "file", encoding: "base64", size: 11, content: b64("line1\nline2\nline3") },
  });
  const file = await readRepoFile(octokit, REF, HEAD, "a.py", {});
  assert.equal(file.ok, true);
  if (file.ok) {
    assert.equal(file.text, "line1\nline2\nline3");
    assert.equal(file.totalLines, 3);
    assert.equal(file.sha, HEAD);
  }
  assert.equal(calls.content[0]?.ref, HEAD);
});

test("a line range returns just those lines", async () => {
  const { octokit } = fake({
    content: { type: "file", encoding: "base64", size: 20, content: b64("a\nb\nc\nd\ne") },
  });
  const file = await readRepoFile(octokit, REF, HEAD, "a.py", { startLine: 2, endLine: 3 });
  assert.ok(file.ok);
  if (file.ok) {
    assert.equal(file.text, "b\nc");
    assert.equal(file.startLine, 2);
  }
});

test("a directory, a symlink and a submodule are refused, not read", async () => {
  for (const content of [[{ type: "file" }], { type: "symlink", target: "/etc/passwd" }, { type: "submodule" }]) {
    const { octokit } = fake({ content });
    const file = await readRepoFile(octokit, REF, HEAD, "d", {});
    assert.equal(file.ok, false);
  }
});

test("an empty file is read as empty text, not refused", async () => {
  const { octokit } = fake({ content: { type: "file", encoding: "base64", size: 0, content: "" } });
  const file = await readRepoFile(octokit, REF, HEAD, "__init__.py", {});
  assert.ok(file.ok);
  if (file.ok) {
    assert.equal(file.text, "");
    assert.equal(file.truncated, false);
  }
});

test("a file too big for the contents API is refused with a reason", async () => {
  const { octokit } = fake({ content: { type: "file", encoding: "none", size: 5_000_000, content: "" } });
  const file = await readRepoFile(octokit, REF, HEAD, "big.bin", {});
  assert.equal(file.ok, false);
  if (!file.ok) {
    assert.match(file.reason, /large|size/i);
  }
});

test("text past the cap is cut and flagged", async () => {
  const { octokit } = fake({
    content: { type: "file", encoding: "base64", size: 300_000, content: b64("y".repeat(300_000)) },
  });
  const file = await readRepoFile(octokit, REF, HEAD, "big.txt", {});
  assert.ok(file.ok);
  if (file.ok) {
    assert.equal(file.truncated, true);
    assert.ok(file.text.length <= 70_000);
  }
});

test("a secret straddling the cap is redacted whole, not cut down to its first characters", async () => {
  const token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0";
  const text = "x".repeat(59_989) + " " + token + " tail";
  const { octokit } = fake({
    content: { type: "file", encoding: "base64", size: text.length, content: b64(text) },
  });
  const file = await readRepoFile(octokit, REF, HEAD, "log.txt", {});
  assert.ok(file.ok);
  if (file.ok) {
    assert.equal(file.truncated, true);
    assert.ok(!file.text.includes(token.slice(0, 10)), "the head of the token leaked past the cap");
  }
});

test("a missing file is a plain refusal, not a crash", async () => {
  const error = Object.assign(new Error("Not Found"), { status: 404 });
  const { octokit } = fake({ contentError: error });
  const file = await readRepoFile(octokit, REF, HEAD, "nope.py", {});
  assert.equal(file.ok, false);
  if (!file.ok) {
    assert.match(file.reason, /not found/i);
  }
});

test("a secret in a file is scrubbed before it is returned", async () => {
  const token = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0";
  const { octokit } = fake({
    content: { type: "file", encoding: "base64", size: 60, content: b64(`GITHUB_TOKEN=${token}`) },
  });
  const file = await readRepoFile(octokit, REF, HEAD, ".env", {});
  assert.ok(file.ok);
  assert.ok(!JSON.stringify(file).includes(token));
});

test("the file listing is filtered by prefix, only files, and capped", async () => {
  const tree = [
    { path: "internal", type: "tree" },
    { path: "internal/a.py", type: "blob" },
    { path: "internal/b.py", type: "blob" },
    { path: "docs/c.md", type: "blob" },
  ];
  const { octokit } = fake({ tree });
  const listing = await listRepoFiles(octokit, REF, HEAD, { prefix: "internal/" });
  assert.deepEqual(listing.paths, ["internal/a.py", "internal/b.py"]);
  assert.equal(listing.truncated, false);
});

test("a listing GitHub itself truncated says so", async () => {
  const { octokit } = fake({ tree: [{ path: "a.py", type: "blob" }], truncatedTree: true });
  const listing = await listRepoFiles(octokit, REF, HEAD, {});
  assert.equal(listing.truncated, true);
});

test("a live listing past the cap is cut to 2,000 paths and flagged", async () => {
  const tree = Array.from({ length: 2_050 }, (_, i) => ({ path: `internal/f${i}.py`, type: "blob" }));
  const { octokit } = fake({ tree });
  const listing = await listRepoFiles(octokit, REF, HEAD, {});
  assert.equal(listing.paths.length, 2_000);
  assert.equal(listing.truncated, true);
});
