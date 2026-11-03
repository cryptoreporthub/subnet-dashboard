# R0.8b — eval vs production tool paths

Pin: PR #1522 head `50e231f3` production paths unchanged; eval fixes are eval-branch only.

| Tool | Production path | Eval path (`session.purpose === "eval"`) | Fidelity gap |
|------|-----------------|------------------------------------------|--------------|
| `read_repo_file` | `readRepoFile(octokit, ref, pr.headSha \| pr.baseSha, path)` from GitHub contents API | `repo.json`: `files[path]` at **head**; `baseFiles[path]` at **base** (no head fallback) | Fixture trees are sparse (only paths in the case); unchanged paths may be absent from `baseFiles` → `not in this fixture` (GitHub would still serve the blob at base). |
| `get_pr_diff` | Live compare via `readDiff(octokit, ref, { head, base, paths })` with secret scrub + caps | `diff.json` + stale-head check against `pr.json` | Eval diff is pinned JSON, not live GitHub compare; scrubbing matches prod via shared `repo.ts` helpers on prod path only. |
| `list_repo_files` | Git tree at `pr.headSha` or `pr.baseSha` via API | Always lists keys of `repo.files` (prefix filter + cap) | **At base**, eval lists head fixture keys, not the base tree; use `read_repo_file` for known paths. |
| `check_gate_state` | `readPr` + `readGateState(octokit, kv, ref, headSha)` | Merge `pr.json` + `gate.json`; throws if `gate.headSha !== pr.headSha` | Matches prod shape; no live KV/GitHub reviewer polling. |
| `compare_suite_runs` | JUnit artifacts + `recordSuiteComparison` + flake list | No runner: returns `gate.json` suite pin (`clean` → clean diff); carry uses `pr.files` not git compare | Eval cannot exercise artifact fetch; carry-over file set is PR file list, not `changedBetween` superset. |

**R0.8a fix (this branch):** eval `read_repo_file` at `base` reads **`baseFiles` only** (`review-gate-bot/tests/tools.test.ts`).
