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
 * Parse the flake file. A malformed line throws: a typo in this file silently
 * drops a flake, and a silently shorter list is a gate that fails open on the
 * test it was meant to excuse.
 */
export function parseFlakeList(text: string, source = "known-flakes.txt"): FlakeList {
  const ids: string[] = [];
  const errors: string[] = [];
  text.split(/\r?\n/).forEach((line, index) => {
    const body = line.replace(/#.*$/, "").trim();
    if (body === "") {
      return;
    }
    if (!/^[\w./[\]=-]+::[\w./[\]= -]+$/.test(body)) {
      errors.push(`line ${index + 1}: ${JSON.stringify(body)} is not \`classname::name\``);
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
