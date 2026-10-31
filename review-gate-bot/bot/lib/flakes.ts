import { readFileSync } from "node:fs";

/**
 * The committed flake list, `known-flakes.txt` next to `package.json`.
 *
 * Read from disk rather than taken from a tool argument: a caller-supplied
 * flake list lets whoever calls `compare_suite_runs` excuse any regression by
 * naming it, which is a gate that approves whatever it is told to approve.
 */

const FLAKE_FILE = new URL("../../known-flakes.txt", import.meta.url);

export type FlakeList = {
  ids: readonly string[];
  /** The file the ids came from, for an audit line. */
  source: string;
};

/**
 * The line without its comment. A `#` starts a comment only at the start of the line or after
 * whitespace, and only outside the brackets of a parameter id. So `test_a[#1]` and
 * `test_a[hello #1]` keep their `#`, and `test_a[x]  # note` drops the note.
 */
function stripComment(line: string): string {
  let depth = 0;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === "[") {
      depth += 1;
    } else if (char === "]" && depth > 0) {
      depth -= 1;
    } else if (char === "#" && depth === 0 && (i === 0 || /\s/.test(line[i - 1]))) {
      return line.slice(0, i);
    }
  }
  return line;
}

/**
 * Parse the flake file. A malformed line throws: a typo in this file silently
 * drops a flake, and a silently shorter list is a gate that fails open on the
 * test it was meant to excuse.
 */
export function parseFlakeList(text: string, source = "known-flakes.txt"): FlakeList {
  const ids: string[] = [];
  const errors: string[] = [];
  text.split(/\r?\n/).forEach((line, index) => {
    const body = stripComment(line).trim();
    if (body === "") {
      return;
    }
    // Structural, not a character class: pytest allows nearly anything inside
    // a parameter id. Only the separator has to be there, with something on
    // both sides.
    const separator = body.indexOf("::");
    if (separator <= 0 || separator === body.length - 2) {
      errors.push(`line ${index + 1}: ${JSON.stringify(body)} is not \`classname::name\``);
      return;
    }
    // A file-path node id (`tests/test_x.py::test_a`) is what pytest prints, but
    // JUnit reports the dotted classname, so that entry would never match.
    const classname = body.slice(0, separator);
    if (/[\s/]/.test(classname) || classname.endsWith(".py")) {
      errors.push(
        `line ${index + 1}: ${JSON.stringify(classname)} is not a JUnit classname (use \`tests.test_x\`, not a file path); it would never match`,
      );
      return;
    }
    ids.push(body);
  });
  if (errors.length > 0) {
    throw new Error(`known-flakes: ${errors.join("; ")}`);
  }
  return { ids, source };
}

let cached: FlakeList | undefined;

/** The committed list. Read once per process. */
export function knownFlakes(): FlakeList {
  cached ??= parseFlakeList(readFileSync(FLAKE_FILE, "utf8"));
  return cached;
}
