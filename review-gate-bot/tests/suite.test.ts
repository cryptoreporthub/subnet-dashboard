import assert from "node:assert/strict";
import test from "node:test";
import { carryBlockingFiles, carryDecision, diffJunit, parseJunit } from "../bot/lib/suite.js";

function junit(cases: { name: string; outcome?: "failed" | "error" | "skipped" }[]): string {
  const body = cases
    .map(({ name, outcome }) => {
      const child =
        outcome === "failed"
          ? '<failure message="boom">trace</failure>'
          : outcome === "error"
            ? '<error message="kaput">trace</error>'
            : outcome === "skipped"
              ? "<skipped/>"
              : "";
      return `<testcase classname="tests.test_x" name="${name}">${child}</testcase>`;
    })
    .join("");
  return `<?xml version="1.0"?><testsuites><testsuite>${body}</testsuite></testsuites>`;
}

test("parseJunit reads outcomes from nested children", () => {
  const cases = parseJunit(junit([{ name: "a" }, { name: "b", outcome: "failed" }, { name: "c", outcome: "skipped" }]));
  assert.deepEqual(
    cases.map((c) => [c.name, c.outcome]),
    [
      ["a", "passed"],
      ["b", "failed"],
      ["c", "skipped"],
    ],
  );
  assert.equal(cases[1]?.detail, "boom");
});

test("a self-closing testcase parses as passed", () => {
  const cases = parseJunit('<testsuite><testcase classname="t" name="ok"/></testsuite>');
  assert.equal(cases.length, 1);
  assert.equal(cases[0]?.outcome, "passed");
});

test("a failure present at both base and head is pre-existing, not a regression", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a", outcome: "failed" }]),
    headXml: junit([{ name: "a", outcome: "failed" }]),
  });
  assert.equal(diff.clean, true);
  assert.deepEqual(diff.preExisting, ["tests.test_x::a"]);
  assert.deepEqual(diff.newFailures, []);
});

test("a failure only at head is a new failure", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a" }]),
    headXml: junit([{ name: "a" }, { name: "b", outcome: "failed" }]),
  });
  assert.equal(diff.clean, false);
  assert.deepEqual(diff.newFailures, ["tests.test_x::b"]);
});

test("a known flake absent at base is recorded as flaky, not a regression", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a" }]),
    headXml: junit([{ name: "a" }, { name: "flake", outcome: "failed" }]),
    knownFlakes: ["tests.test_x::flake"],
  });
  assert.equal(diff.clean, true);
  assert.deepEqual(diff.flakyRetriedOk, ["tests.test_x::flake"]);
});

test("a fixed failure is reported as fixed", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a", outcome: "failed" }]),
    headXml: junit([{ name: "a" }]),
  });
  assert.deepEqual(diff.fixed, ["tests.test_x::a"]);
});

test("an error counts as a failure", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a" }]),
    headXml: junit([{ name: "a", outcome: "error" }]),
  });
  assert.equal(diff.clean, false);
});

// --- Blocker 3: zero testcases is a failure, not a clean suite -------------

test("an empty head report is invalid, never clean", () => {
  const diff = diffJunit({ baseXml: junit([{ name: "a" }]), headXml: "" });
  assert.equal(diff.clean, false, "an empty report must not read as a clean suite");
  assert.equal(diff.invalid, "zero-testcases");
  assert.deepEqual(diff.counts, { base: 1, head: 0 });
});

test("a report with only skipped tests still has testcases, so it is not invalid", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a" }]),
    headXml: junit([{ name: "a", outcome: "skipped" }]),
  });
  assert.equal(diff.invalid, undefined);
  assert.equal(diff.clean, true);
});

test("a truncated report that lost every testcase cannot pass the gate", () => {
  const truncated = '<?xml version="1.0"?><testsuites><testsuite name="pytest" errors="0"';
  const diff = diffJunit({ baseXml: junit([{ name: "a" }]), headXml: truncated });
  assert.equal(diff.clean, false);
  assert.equal(diff.invalid, "zero-testcases");
});

// --- Blocker 3: deny-by-default carry-over paths ---------------------------

test("prose and images do not block a carry-over", () => {
  assert.deepEqual(
    carryBlockingFiles(["docs/readme.md", "cursor-agents-communication/x.md", "CHANGELOG.md", "artifacts/a.png"]),
    [],
  );
});

test("every non-prose file blocks a carry-over, whatever its extension", () => {
  const files = [
    "internal/council/resolver.py",
    "scripts/fly_disable_worker_v2.sh",
    "templates/index.html",
    "Dockerfile",
    "requirements.txt",
    ".github/workflows/ci-smoke.yml",
    "static/app.js",
    "data/predictions.json",
    "config/tenants.yaml",
    "Procfile",
  ];
  assert.deepEqual(carryBlockingFiles(files), files);
});

test("the files that would have carried as docs-only in the old rule now block", () => {
  // Claude's counter-example: test_hold_shadows.py asserts on a Jinja template,
  // so a .html change reaches pytest. Under the old allowlist it carried.
  assert.deepEqual(carryBlockingFiles(["templates/hold_shadows.html"]), ["templates/hold_shadows.html"]);
  // And a workflow file that runs the suite is not prose either.
  assert.deepEqual(carryBlockingFiles([".github/workflows/fly.yml"]), [".github/workflows/fly.yml"]);
});

test("PR 1519's head blocks a carry-over because of the .sh", () => {
  const pr1519Files = [
    ".github/workflows/fly-enable-v2.yml",
    "cursor-agents-communication/fly-worker-split-v2-lock.md",
    "cursor-agents-communication/split-v2-rollback-runbook.md",
    "scripts/fly_disable_worker_v2.sh",
  ];
  assert.deepEqual(carryBlockingFiles(pr1519Files), [
    ".github/workflows/fly-enable-v2.yml",
    "scripts/fly_disable_worker_v2.sh",
  ]);
});

// --- Blocker 3: carry only from a recorded clean SHA ----------------------

test("a prose-only head may carry, but only from a SHA recorded clean", () => {
  const changed = ["docs/readme.md"];
  assert.deepEqual(carryDecision({ changedFiles: changed, recordedAtCarryFrom: "clean" }), { ok: true });

  for (const state of ["missing", "regressed", "carried"] as const) {
    assert.deepEqual(
      carryDecision({ changedFiles: changed, recordedAtCarryFrom: state }),
      { ok: false, reason: "no-clean-source" },
      `carrying from a ${state} result must be refused`,
    );
  }
});

test("a code change blocks a carry even when the source SHA was clean", () => {
  const decision = carryDecision({ changedFiles: ["internal/x.py"], recordedAtCarryFrom: "clean" });
  assert.equal(decision.ok, false);
  if (!decision.ok) {
    assert.equal(decision.reason, "code-changed");
    assert.deepEqual(decision.blocking, ["internal/x.py"]);
  }
});
