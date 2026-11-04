# Oracle generator for the hard exam

`evals/fixtures/hard-*/oracle.json` says what the real bot code does for each of the 21 cases, at the base and at the
planted head: pytest results, parser outputs, timing classes, the concurrency run. Nobody typed those values in. This
directory is the program that produced them, and `oracle.json` is reproducible from it.

| file | what it is |
| --- | --- |
| `gen.py` | builds `pr.json`, `gate.json`, `diff.json`, `repo.json`, `oracle.json` for every `evals/fixtures/hard-*` directory |
| `oracles.py` | the behavioural oracles that run the app's python (pytest, the parser, the grace logic) under an injected clock |
| `concurrency.ts` | the two-process and head-moved-during-review harness for the concurrency cases (run with `tsx`) |
| `../scaling.ts` | the timing probe for case 9 (doubling ratio, noise floor, absolute cap); the generator imports its budget, not its timings |

## The exact commands

Run from `review-gate-bot/`. Use `npm run`, or the command it wraps.

| goal | npm | command |
| --- | --- | --- |
| regenerate the fixtures in place | `npm run oracle:regen -- --python <venv>/bin/python` | `python3 evals/oracle-gen/gen.py --python <venv>/bin/python` |
| check that the committed fixtures equal a fresh run (full) | `npm run oracle:check -- --python <venv>/bin/python` | `python3 evals/oracle-gen/gen.py --check --python <venv>/bin/python` |
| fast check: diffs, pins, repo/pr/gate files only (no python deps, no node) | `npm run oracle:check:fast` | `python3 evals/oracle-gen/gen.py --check --skip-behavior` |

`--python` (or the `ORACLE_PYTHON` env var) names a python that has the app's `requirements.txt` plus `pytest`
installed. `--node` (or `ORACLE_NODE`) names node >= 22.13 and defaults to `node` on the path. `tsx` comes from
`npm ci` in `review-gate-bot/`.

One-time setup for the full run:

```
python3 -m venv /tmp/oracle-venv
/tmp/oracle-venv/bin/pip install -r ../requirements.txt pytest
npm ci
```

## Why the output is the same on every machine

- Every source file is read from one pinned commit, `SOURCE_COMMIT` in `gen.py` (88b72c5b, the #1522 head the exam is
  built on), with `git show`. The working tree, the branch you are on and uncommitted edits do not matter.
- The python tree the oracles run in is a `git archive` of that same commit, unpacked in a temp dir.
- Time is injected. The grace-period oracles read `oracles.CLOCK`, not the machine clock, so "after 48h" is an
  exact, named instant (`T0 + 172800 s`), and the 47:59:59 / 48:00:00 boundary is part of the oracle.
- No duration or timing is written to `oracle.json`. The JWT case records the patterns, the measurement budget and the
  class each pattern lands in (fails the ratio, fails the cap, passes). Noise only adds time, so the generator measures
  again (up to 8 times) when a loaded machine pushes a class the wrong way, and fails if no run lands in the expected
  classes. `tests/hard-scaling.test.ts` measures live with the same rule.
- JSON is written with sorted keys and fixed indentation, and diffs come from `difflib`, so output bytes are stable.

Two full runs on one machine were byte-identical. `--check` exits 1 and names the file when a fixture differs.

## Requirements and limits

- The clone must contain the pinned commits: `88b72c5b` and the two #1522 rounds the past-miss diffs come from,
  `44ce7ea5` and `d578603e`. A shallow CI checkout does not, and the generator says so and exits instead of guessing.
  `tests/hard-oracle-gen.test.ts` skips its regeneration check in that case, with the reason in the test output.
- If #1522 is squash-merged, those commits can disappear from the default history. Fetch them from the PR ref
  (`git fetch origin pull/1522/head`) or pass `--source-commit <sha>` after confirming the python tree is
  the same, then update `SOURCE_COMMIT` and regenerate. Do not repoint it casually: the case 13 corpus comes from the
  test files at that commit and is part of the oracle.
- Changing a case's prompt or accept-list does not need a regeneration. Changing the planted diff, the pinned commit, or
  an oracle does, and `tests/hard-fixtures.test.ts` pins the diff hashes so a silent change fails the suite.
