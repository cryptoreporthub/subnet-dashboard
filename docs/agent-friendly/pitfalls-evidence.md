# Agent pitfalls evidence (subnet-dashboard)

Counts are from **git history and GitHub**, not estimates. Joshua comment attribution is **heuristic** (unsigned `cryptoreporthub` comments minus bot markers).

## Top pitfall classes

| Rank | Class | Count / signal | Example |
|------|-------|----------------|---------|
| 1 | **Ops honesty / partial fetch** | 28+ commits touching `live_subnets` / `refresh_complete` / stale in last 500 on `main` | `1b6ed45a` fix(live_subnets): propagate refresh_complete to cache readers (#1364) |
| 2 | **Metrics / coverage false PASS** | 19+ commits; Joshua theme `honesty_semantics` 76 in filtered comments | `834657e8` fix(gecko): block sub-hourly cadence false PASS (#1435) |
| 3 | **Review without pin / weak evidence** | 119 filtered comments mention pinned head | PR #1434 threads at `7f9fc640`, `935a473f` |
| 4 | **Silent router import failure** | Structural: 16 `_FOO_ROUTES` flags in `server.py` | If import fails, slice routes vanish while monolith routes in `server.py` remain |
| 5 | **Persistence races** | 5+ commits on atomic/fsync/tmp | `25b67448` fix(file_utils): fsync in safe_write_json (#1422) |
| 6 | **Missing imports / copy-paste** | 6+ import-fix commits | `2c20997c` add Tuple import in whale scanner (#1423) |
| 7 | **Second server foundation** | CI guards + historical outage | `f3371f45` CI use server.py; fly guard blocks `server_original.py` |
| 8 | **Worker / telegram split mistakes** | 39 worker/telegram themed commits in last 500 | `cd0c37b6` worker-only summary bot poll (#1389) |
| 9 | **RPC 429 / chain cooldown** | 10+ commits | `2ba0998e` shared RPC 429 cooldown (#1426) |
| 10 | **Revert / hotfix loops** | 11 revert/hotfix commits in last 500 | `d32f5384` Restore Fly web stability (#452) |

## GitHub Joshua steering sample (filtered)

Uncertainty: **189** comments passed bot filter; some may still be Claude-authored posts on the shared account.

Themes in filtered set:

- `explicit_verdicts`: 156
- `review_at_pinned_head`: 119
- `require_tests`: 100
- `honesty_semantics`: 76
- `draft_no_deploy`: 40

Example unsigned review line (PR #1435): `**Verdict: PASS** at head \`e4ec6cec\`` with pytest regression cited.

## Structural fixes mapped to pitfalls

| Pitfall | Make impossible by |
|---------|-------------------|
| Silent slice drop | `mount_registry.load_all()` must run in CI; remove try/except import gates |
| False green metrics | Typed status fields + tests that fail if `ok: true` without `refresh_complete` |
| Non-atomic state | Single `safe_write_json` entry; AST deny other `open(..., 'w')` under `data/` |
| Wrong review SHA | PR check prints `git rev-parse HEAD`; review template in `.github/pull_request_template.md` |
| Duplicate CONTRACT | `test_contract_entries_are_unique` (merged in prototype) |

## Recall note

`/recall` over agent transcripts: **no JSONL corpus** on this VM (`~/.cursor/projects/**/agent-transcripts` empty). Used shared record: GitHub PR comments, `AGENTS.md`, `cursor-agents-communication/model-guide.md`, commit log.
