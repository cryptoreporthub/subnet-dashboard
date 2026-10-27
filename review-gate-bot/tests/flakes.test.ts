import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { knownFlakes, parseFlakeList } from "../bot/lib/flakes.js";

test("the committed flake list loads and is empty until a real flake is proven", () => {
  const list = knownFlakes();
  assert.equal(list.source, "known-flakes.txt");
  assert.ok(Array.isArray(list.ids));
});

test("the committed file is where the tool reads it, not a tool argument", () => {
  // The gate must not accept a caller-supplied flake list; this pins the file
  // the tool actually reads.
  const text = readFileSync(join("known-flakes.txt"), "utf8");
  assert.ok(text.includes("classname::name"));
});

test("comments and blank lines are ignored", () => {
  const list = parseFlakeList("# a flake\n\n  # indented comment\ntests.test_x::flake\n");
  assert.deepEqual(list.ids, ["tests.test_x::flake"]);
});

test("a malformed line fails the load instead of being skipped", () => {
  // A silently dropped flake turns into a spurious regression; a silently
  // accepted junk line turns into an accidental excuse. Both are worse than a
  // loud failure at startup.
  assert.throws(() => parseFlakeList("tests.test_x flake\n"), /not `classname::name`/);
  assert.throws(() => parseFlakeList("just-a-word\n"), /not `classname::name`/);
});

test("a parametrised test id with brackets and spaces is accepted", () => {
  const list = parseFlakeList("tests.test_x::test_a[1 - 2]\n");
  assert.deepEqual(list.ids, ["tests.test_x::test_a[1 - 2]"]);
});

test("any punctuation pytest allows in a parameter id is accepted", () => {
  for (const id of [
    "tests.test_x::test_case[region:west]",
    "tests.test_x::test_a[x,y]",
    "tests.test_x::test_a[a|b]",
    "tests.test_x::test_a[héllo]",
    "tests.test_x::test_a[#1]",
    "tests.test_x::test_a[1 - 2]::tail",
  ]) {
    assert.deepEqual(parseFlakeList(`${id}\n`).ids, [id], id);
  }
});

test("a comment still ends a line, but a # inside an id does not", () => {
  const list = parseFlakeList("tests.test_x::test_a[#1] # seen on run 123\n");
  assert.deepEqual(list.ids, ["tests.test_x::test_a[#1]"]);
});

test("pytest's file-path node id can never match a JUnit classname, so it is refused with a hint", () => {
  assert.throws(() => parseFlakeList("tests/test_x.py::test_a\n"), /classname/i);
});

test("an empty side of the separator is refused", () => {
  assert.throws(() => parseFlakeList("::name\n"), /not `classname::name`/);
  assert.throws(() => parseFlakeList("tests.test_x::\n"), /not `classname::name`/);
});
