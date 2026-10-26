import assert from "node:assert/strict";
import test from "node:test";
import { diffJunit, parseJunit, pytestReachable } from "../bot/lib/suite.js";

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

test("docs-only changes are not pytest-reachable", () => {
  assert.deepEqual(
    pytestReachable(["docs/readme.md", "cursor-agents-communication/x.md", "CHANGELOG.md"]),
    [],
  );
});

test("a python file, conftest, requirements or pytest config is reachable", () => {
  const reachable = pytestReachable([
    "internal/council/resolver.py",
    "tests/conftest.py",
    "requirements.txt",
    "pytest.ini",
    "pyproject.toml",
  ]);
  assert.equal(reachable.length, 5);
});

test("a shell script and a data json are reachable", () => {
  const reachable = pytestReachable(["scripts/fly_disable_worker_v2.sh", "data/predictions.json"]);
  assert.deepEqual(reachable, ["scripts/fly_disable_worker_v2.sh", "data/predictions.json"]);
});

test("PR 1519's docs-plus-one-echo-line head is pytest-reachable because of the .sh", () => {
  const pr1519Files = [
    ".github/workflows/fly-enable-v2.yml",
    "cursor-agents-communication/fly-worker-split-v2-lock.md",
    "cursor-agents-communication/split-v2-rollback-runbook.md",
    "scripts/fly_disable_worker_v2.sh",
  ];
  assert.deepEqual(pytestReachable(pr1519Files), ["scripts/fly_disable_worker_v2.sh"]);
});
