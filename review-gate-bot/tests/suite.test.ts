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

test("a `>` inside a self-closing failure's message does not end the tag", () => {
  const cases = parseJunit(
    '<testsuite><testcase classname="t" name="x"><failure message="1 > 0" /></testcase></testsuite>',
  );
  assert.equal(cases[0]?.outcome, "failed");
  assert.equal(cases[0]?.detail, "1 > 0");
});

test("a `>` inside a testcase name does not merge it with the next testcase", () => {
  const cases = parseJunit(
    '<testsuite><testcase classname="t" name="a > b"/><testcase classname="t" name="c"><failure message="boom"/></testcase></testsuite>',
  );
  assert.deepEqual(
    cases.map((c) => [c.name, c.outcome]),
    [
      ["a > b", "passed"],
      ["c", "failed"],
    ],
  );
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

test("an empty base report is invalid too: a zero-testcase base cannot prove a head clean", () => {
  const diff = diffJunit({ baseXml: "", headXml: junit([{ name: "a" }]) });
  assert.equal(diff.clean, false, "a base with nothing to compare against must not read as clean");
  assert.equal(diff.invalid, "zero-testcases");
  assert.deepEqual(diff.counts, { base: 0, head: 1 });
});

test("a test skipped at head that passed at base is refused, while skipped at both is not", () => {
  const newly = diffJunit({
    baseXml: junit([{ name: "a" }]),
    headXml: junit([{ name: "a", outcome: "skipped" }]),
  });
  assert.equal(newly.invalid, "newly-skipped");
  assert.equal(newly.clean, false);

  const bothSkipped = diffJunit({
    baseXml: junit([{ name: "a", outcome: "skipped" }]),
    headXml: junit([{ name: "a", outcome: "skipped" }]),
  });
  assert.equal(bothSkipped.invalid, undefined);
  assert.equal(bothSkipped.clean, true);
});

test("a truncated report that lost every testcase cannot pass the gate", () => {
  const truncated = '<?xml version="1.0"?><testsuites><testsuite name="pytest" errors="0"';
  const diff = diffJunit({ baseXml: junit([{ name: "a" }]), headXml: truncated });
  assert.equal(diff.clean, false);
  assert.equal(diff.invalid, "zero-testcases");
});

// --- A report that is cut off after some testcases is not a report ---------

const TRUNCATED_AFTER_PASSES =
  '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="a"/>';

test("a head report cut off after passing testcases cannot pass the gate", () => {
  const diff = diffJunit({ baseXml: junit([{ name: "a" }]), headXml: TRUNCATED_AFTER_PASSES });
  assert.equal(diff.clean, false, "an incomplete run proves nothing");
  assert.equal(diff.invalid, "malformed-xml");
  assert.equal(diff.counts.head, 1, "the testcase was readable, the document was not");
});

test("a base report cut off after testcases is invalid too", () => {
  const diff = diffJunit({ baseXml: TRUNCATED_AFTER_PASSES, headXml: junit([{ name: "a" }]) });
  assert.equal(diff.clean, false);
  assert.equal(diff.invalid, "malformed-xml");
});

test("parseJunit refuses a document with mismatched or unclosed elements", () => {
  assert.throws(() => parseJunit(TRUNCATED_AFTER_PASSES), /malformed/i);
  assert.throws(
    () => parseJunit('<testsuite><testcase classname="t" name="a"></testsuite></testcase>'),
    /malformed/i,
  );
  assert.throws(() => parseJunit('<testsuite><testcase classname="t" name="a"/></testsuite><testsuite/>'), /malformed/i);
});

test("a report cut off inside a tag is malformed", () => {
  assert.throws(() => parseJunit('<testsuite><testcase classname="t" name="a"/></testsui'), /malformed/i);
});

test("valid XML features pytest can emit are not mistaken for damage", () => {
  const xml =
    '<?xml version="1.0" encoding="utf-8"?><!-- generated --><testsuites><testsuite name="pytest">' +
    '<testcase classname="t" name="a"><failure message="x &gt; y &lt; z">a > b</failure>' +
    "<system-out><![CDATA[1 < 2 && </testcase> ]]></system-out></testcase>" +
    '<testcase classname="t" name="b"/></testsuite></testsuites>';
  const cases = parseJunit(xml);
  assert.deepEqual(
    cases.map((c) => [c.name, c.outcome]),
    [
      ["a", "failed"],
      ["b", "passed"],
    ],
  );
});

// --- What pytest really writes ----------------------------------------------

test("a self-closing <failure /> or <error /> is a failure, as pytest 9 writes it", () => {
  const xml =
    '<?xml version="1.0"?><testsuites><testsuite name="pytest">' +
    '<testcase classname="tests.test_x" name="fails"><failure message="Failed" /></testcase>' +
    '<testcase classname="tests.test_x" name="errs"><error message="failed on setup" /></testcase>' +
    '<testcase classname="tests.test_x" name="ok"/></testsuite></testsuites>';
  assert.deepEqual(
    parseJunit(xml).map((c) => [c.name, c.outcome]),
    [
      ["fails", "failed"],
      ["errs", "error"],
      ["ok", "passed"],
    ],
  );
  const diff = diffJunit({ baseXml: junit([{ name: "ok" }]), headXml: xml });
  assert.equal(diff.clean, false);
  assert.deepEqual(diff.newFailures, ["tests.test_x::errs", "tests.test_x::fails"]);
});

test("single-quoted attributes and a testcase with no name still count", () => {
  const xml =
    "<testsuites><testsuite><testcase classname='tests.test_x' name='single'><failure message='boom'>x</failure></testcase>" +
    '<testcase classname="tests.test_x"><failure message="anonymous"/></testcase></testsuite></testsuites>';
  const cases = parseJunit(xml);
  assert.equal(cases.length, 2);
  assert.deepEqual(
    cases.map((c) => c.outcome),
    ["failed", "failed"],
  );
  assert.equal(diffJunit({ baseXml: junit([{ name: "ok" }]), headXml: xml }).clean, false);
});

test("a commented-out testcase is not counted", () => {
  const xml = '<testsuites><testsuite><!-- <testcase classname="t" name="ghost"/> --><testcase classname="t" name="real"/></testsuite></testsuites>';
  assert.deepEqual(
    parseJunit(xml).map((c) => c.name),
    ["real"],
  );
});

test("a CDATA block holding </testcase> does not swallow the failure that precedes it", () => {
  const xml =
    '<testsuites><testsuite><testcase classname="t" name="a"><system-out><![CDATA[</testcase>]]></system-out>' +
    '<failure message="late"/></testcase></testsuite></testsuites>';
  assert.equal(parseJunit(xml)[0]?.outcome, "failed");
});

// --- Blocker 3: deny-by-default carry-over paths ---------------------------

test("prose and images do not block a carry-over", () => {
  assert.deepEqual(
    carryBlockingFiles(["docs/readme.md", "cursor-agents-communication/x.md", "CHANGELOG.md", "artifacts/a.png"]),
    [],
  );
});

test("a prose or image file that a test reads blocks a carry-over", () => {
  // The suite's own tests read these, so a change to one can flip a result.
  const readByTests = [
    "AGENTS.md",
    "cursor-agents-communication/model-guide.md",
    "DEPLOY.md",
    "static/favicon.svg",
  ];
  assert.deepEqual(carryBlockingFiles(readByTests), readByTests);
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

// --- Second review: a report that shrinks, and one built to be slow ---------

test("a base test missing at head cannot read clean, however few are missing", () => {
  const many = (n: number) => junit(Array.from({ length: n }, (_, i) => ({ name: `t${i}` })));
  const trimmed = diffJunit({ baseXml: many(100), headXml: many(95) });
  assert.equal(trimmed.clean, false, "five base tests are gone, and the gate cannot tell a removal from a pass");
  assert.equal(trimmed.invalid, "baseline-test-missing");
  assert.equal(trimmed.missing.length, 5);
  assert.deepEqual(trimmed.counts, { base: 100, head: 95 });
  assert.equal(diffJunit({ baseXml: many(100), headXml: many(120) }).clean, true, "new tests at head are fine");
});

test("a base failing test absent at head is not a fixed failure: it cannot read clean", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a", outcome: "failed" }, { name: "b" }]),
    headXml: junit([{ name: "b" }]),
  });
  assert.equal(diff.clean, false, "a removed failing test looks fixed, and the gate cannot tell the two apart");
  assert.equal(diff.invalid, "baseline-test-missing");
  assert.deepEqual(diff.missing, ["tests.test_x::a"]);
});

test("a test newly skipped at head cannot read clean", () => {
  const diff = diffJunit({
    baseXml: junit([{ name: "a" }, { name: "b" }]),
    headXml: junit([{ name: "a", outcome: "skipped" }, { name: "b" }]),
  });
  assert.equal(diff.clean, false);
  assert.equal(diff.invalid, "newly-skipped");
  assert.deepEqual(diff.skipped, ["tests.test_x::a"]);
});

test("a malformed report made of unclosed testcases is rejected quickly", () => {
  const hostile = '<testsuites><testsuite>' + '<testcase classname="t" name="a">'.repeat(60_000);
  const started = Date.now();
  const diff = diffJunit({ baseXml: junit([{ name: "a" }]), headXml: hostile });
  assert.equal(diff.invalid, "malformed-xml");
  assert.ok(Date.now() - started < 1_000, `took ${Date.now() - started} ms`);
});
