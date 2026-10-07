# Deploy vehicle — Soul-map compaction (Runbook v4)

**Date (UTC):** 2026-09-08  
**Operator:** Mission Control (Joshua pre-delegated)  
**Live tip at restart:** `dee9e13` (data-plane compaction only; code image unchanged)

## Census before
- Pre-compact census (tooling): #1215 / run `34173330514` — `total_bytes≈24239668`, `feedback_logs` 10856966B (44.79%), len=429
- Dry-run baseline: run `34179691438`

```
TOP_LEVEL_KEY_INVENTORY: ["adversarial_state", "expert_weights", "feedback_logs", "judge_weights", "liveness", "prediction_resolver_scheduler", "score_snapshot_scheduler", "simivision_convictions", "simivision_convictions_updated_at", "soul_map_state"]
FEEDBACK_LOGS_LEN: 429
CURRENT_SIZE_BYTES: 24247814
PROJECTED_SIZE_BYTES: 897246
DRY_RUN_SUCCESS
```

## Execution
- Tool PR: #1216 (`fd58fea1`) — `scripts/compact_soul_map.py` + tests + dry-run WF
- Execute WF PR: #1217 (`0e3d3651`)
- Execute run: `34180031521` **SUCCESS**
- Exit: 0
- Line: `PRE_RESTART_VERIFICATION_PASSED bytes=897245 feedback_logs_len=10`
- **Pinned backup:** `/app/data/soul_map.json.bak-20260908_022616` (byte-matched 24247813)
- **Restart:** `flyctl apps restart subnet-dashboard` at `2026-09-08T02:26:33Z`

## Census after
- +5min: run `34180406122` — `total_bytes=900585`, `feedback_logs` list len=10, all dry-run inventory keys present
- +15min: run `34180925619` — `total_bytes=901696`, `feedback_logs` list len=10, keys intact

## Volume-stat
| when | soul_map size | band 800KB–1.1MB |
|---|---:|---|
| early post-restart | 899440 | PASS |
| +5min | 900585 | PASS |
| +15min | 901696 | PASS |

No resurrection (~24.2MB). No key-drop (~402KB).

## Gate table

| Gate | +5min | +15min | Notes |
|---|---|---|---|
| G1 size ~918KB (800K–1.1M) | PASS 900585 | PASS 901696 | |
| G2 census len≤10 + inventory | PASS | PASS | |
| G3 persist_summary_rmw_ms < ~50ms | FAIL 1185.8 | FAIL 1185.8 (stale sample) | File healthy → **do not restore**; ~85× better than pre-compact ~101s |
| G4 complete + t6/t7 | PASS | PASS | Same gap_timing sample; scheduler `lifecycle=stopped` / `next_run_at=null` — resolver recovery playbook, not compaction restore |
| G5 load/heal < ~2s | PASS 341 / 245 ms | PASS | |

## Expected deepcopy improvement
~26× smaller soul_map blob (24.2MB → ~0.9MB). Per `read_soul_map` docstring, the relic previously starved scoring at ~280 deepcopies per universe score; post-compaction those copies are ~26× cheaper in payload mass.

## Follow-ons
- Cap PR #1218 (`feedback-logs-cap`) — open; merge after G3/scheduler acceptance
- Timeouts unchanged (360s kill-switch stays)
- Backup retained on volume: `soul_map.json.bak-20260908_022616`
