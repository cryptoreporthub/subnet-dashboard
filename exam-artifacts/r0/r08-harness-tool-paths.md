# R0.8b — eval vs production tool paths

Pin: PR #1522 head `50e231f3` production paths unchanged; eval fixes are eval-branch only.

| Tool | Production path | Eval path (`session.purpose === "eval"`) | Fidelity gap |
|------|-----------------|------------------------------------------|--------------|
| `read_repo_file` | `readRepoFile(octokit, ref, pr.headSha \| pr.baseSha, path)` from GitHub contents API | `evalRepoTextAtBase`: **`baseFiles[path]`** if present; else if path in `pr.files` → missing; else unchanged **`files[path]`** | Matches production: unchanged blobs identical at base/head; changed files use `baseFiles`; PR-added absent at base. |
| `get_pr_diff` | Live compare via `readDiff(octokit, ref, { head, base, paths })` with secret scrub + caps | `diff.json` + stale-head check against `pr.json` | Eval diff is pinned JSON, not live GitHub compare; scrubbing matches prod via shared `repo.ts` helpers on prod path only. |
| `list_repo_files` | Git tree at `pr.headSha` or `pr.baseSha` via API | **Head:** `files` keys. **Base:** `evalRepoPathsAtBase` = `baseFiles` keys + unchanged `files` keys (excludes `pr.files` additions) | Sparse fixture trees; unchanged context included at base (R0.8-REVIEW). |
| `check_gate_state` | `readPr` + `readGateState(octokit, kv, ref, headSha)` | Merge `pr.json` + `gate.json`; throws if `gate.headSha !== pr.headSha` | Matches prod shape; no live KV/GitHub reviewer polling. |
| `compare_suite_runs` | JUnit artifacts + `recordSuiteComparison` + flake list | No runner: returns `gate.json` suite pin (`clean` → clean diff); carry uses `pr.files` not git compare | Eval cannot exercise artifact fetch; carry-over file set is PR file list, not `changedBetween` superset. |

**R0.8a fix (this branch):** shared `bot/lib/eval-repo-fixture.ts`; tests `R0.8-1` … `R0.8-5` in `review-gate-bot/tests/tools.test.ts`.
