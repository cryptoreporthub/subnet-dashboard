import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

/**
 * oracle.json is generated, not typed in. These tests keep it that way: the README's commands are the real ones,
 * and (where the pinned commits are in the clone) a fresh run of the generator equals the committed fixtures.
 * The regeneration layer skips, with its reason in the output, when the clone is too shallow to hold the pinned
 * commits. Set ORACLE_PYTHON (a python with ../requirements.txt and pytest) to also run the behavioural layer.
 */
const README = readFileSync("evals/oracle-gen/README.md", "utf8");
const GEN = readFileSync("evals/oracle-gen/gen.py", "utf8");
const PKG = JSON.parse(readFileSync("package.json", "utf8")) as { scripts: Record<string, string> };

const run = (cmd: string, args: string[]) => spawnSync(cmd, args, { encoding: "utf8", timeout: 300_000 });
const hasPython = run("python3", ["--version"]).status === 0;
const pinned = ["88b72c5b", "44ce7ea5", "d578603e"];
const haveCommits = pinned.every((c) => run("git", ["cat-file", "-e", `${c}^{commit}`]).status === 0);
const skipReason = !hasPython ? "python3 is not installed" : !haveCommits ? `this clone lacks ${pinned.join(", ")} (shallow checkout): fetch the PR history, see evals/oracle-gen/README.md` : false;

test("the generator, its oracles and its README ship inside the exam", () => {
  for (const f of ["gen.py", "oracles.py", "concurrency.ts", "README.md"]) {
    assert.ok(existsSync(join("evals/oracle-gen", f)), f);
  }
  assert.ok(existsSync("evals/scaling.ts"));
});

test("the README gives the exact regeneration command, and the generator accepts every flag it names", () => {
  assert.match(README, /python3 evals\/oracle-gen\/gen\.py --python <venv>\/bin\/python/);
  assert.match(README, /python3 evals\/oracle-gen\/gen\.py --check --python <venv>\/bin\/python/);
  assert.match(README, /python3 evals\/oracle-gen\/gen\.py --check --skip-behavior/);
  const flags = new Set(README.match(/--[a-z][a-z-]+/g));
  for (const flag of flags) {
    if (flag === "--python" || flag === "--check" || flag === "--skip-behavior") {
      assert.ok(GEN.includes(`"${flag}"`), `${flag} is a gen.py argument`);
    }
  }
  assert.ok(GEN.includes("SOURCE_COMMIT = \"88b72c5b55ead19d0b5570bbf7f1e7c8d5309e38\""));
  assert.match(README, /88b72c5b/);
});

test("the npm scripts are the commands the README names", () => {
  assert.equal(PKG.scripts["oracle:regen"], "python3 evals/oracle-gen/gen.py");
  assert.equal(PKG.scripts["oracle:check"], "python3 evals/oracle-gen/gen.py --check");
  assert.equal(PKG.scripts["oracle:check:fast"], "python3 evals/oracle-gen/gen.py --check --skip-behavior");
  for (const s of ["oracle:regen", "oracle:check", "oracle:check:fast"]) assert.ok(README.includes(`npm run ${s}`), s);
});

test("no committed oracle.json carries a timing, a duration or a wall-clock stamp", () => {
  for (const d of readdirSync("evals/fixtures").filter((n) => n.startsWith("hard-"))) {
    const text = readFileSync(join("evals/fixtures", d, "oracle.json"), "utf8");
    assert.doesNotMatch(text, /"(?:ms|ms[A-Z0-9_]\w*|(?!capMs|noiseFloorMs)\w*Ms|duration\w*|took\w*)"\s*:/, d);
    assert.doesNotMatch(text, /\bin \d+\.\d+s\b/, `${d}: a pytest duration leaked in`);
  }
});

test("--check, fast layer: a fresh run reproduces the diffs, pins and repo/pr/gate files", { skip: skipReason }, () => {
  const r = run("python3", ["evals/oracle-gen/gen.py", "--check", "--skip-behavior"]);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /oracle-gen --check: ok/);
});

test("--check notices drift: a doctored fixture copy fails and names the file", { skip: skipReason }, () => {
  const copy = mkdtempSync(join(tmpdir(), "fixtures-drift-"));
  try {
    cpSync("evals/fixtures", copy, { recursive: true });
    const victim = join(copy, "hard-weaken-tests", "diff.json");
    writeFileSync(victim, readFileSync(victim, "utf8").replace("def test_", "def test_x_"));
    const r = run("python3", ["evals/oracle-gen/gen.py", "--check", "--skip-behavior", "--fixtures", copy]);
    assert.equal(r.status, 1);
    assert.match(r.stdout, /hard-weaken-tests\/diff\.json: differs/);
    const kept = /generated copy kept in (\S+)\)/.exec(r.stdout)?.[1];
    if (kept) rmSync(kept, { recursive: true, force: true });
  } finally {
    rmSync(copy, { recursive: true, force: true });
  }
});

test(
  "--check, full: oracle.json is reproduced byte for byte (behaviour included)",
  { skip: skipReason || (process.env.ORACLE_PYTHON ? false : "set ORACLE_PYTHON to a venv python with the app requirements and pytest to run the behavioural layer (about 40 s)") },
  () => {
    const r = run("python3", ["evals/oracle-gen/gen.py", "--check"]);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.match(r.stdout, /oracle\.json included/);
  },
);
