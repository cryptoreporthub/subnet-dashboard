import assert from "node:assert/strict";
import test from "node:test";
import {
  guardsRemovedOrRelaxedInPatch,
  guardsRemovedOrRelaxedSection,
} from "../bot/lib/guards-removed-relaxed.js";

test("removed guard: deleted if/assert lines are flagged", () => {
  const patch = ["@@ -1,3 +1,2 @@", "-if netuids:", "-    return last_good", "+    return snapshot", ""].join("\n");
  const flags = guardsRemovedOrRelaxedInPatch("reader.py", patch);
  assert.equal(flags.length, 1);
  assert.equal(flags[0]?.kind, "removed");
  assert.match(flags[0]?.line ?? "", /^if netuids:/);
});

test("relaxed guard: shorter if on the next + line is flagged as relaxed", () => {
  const patch = [
    "@@ -10,3 +10,3 @@",
    "-if owner and cycle_ok and fresh:",
    "+if owner and cycle_ok:",
    "     write()",
    "",
  ].join("\n");
  const flags = guardsRemovedOrRelaxedInPatch("worker.py", patch);
  assert.equal(flags.length, 1);
  assert.equal(flags[0]?.kind, "relaxed");
});

test("non-guard deletions are ignored", () => {
  const patch = ["@@ -1,2 +1,1 @@", '-logger.info("tick")', '+logger.info("tick")', ""].join("\n");
  assert.deepEqual(guardsRemovedOrRelaxedInPatch("x.py", patch), []);
});

test("section is empty when nothing flagged", () => {
  assert.equal(guardsRemovedOrRelaxedSection([]), "");
});

test("section lists each flag for the reviewer", () => {
  const section = guardsRemovedOrRelaxedSection([
    { path: "a.py", kind: "removed", line: "assert x" },
  ]);
  assert.match(section, /Guards removed or relaxed/);
  assert.match(section, /`a.py`/);
  assert.match(section, /assert x/);
});
