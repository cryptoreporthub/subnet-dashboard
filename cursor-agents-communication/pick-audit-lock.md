# Pick selection audit lock (nightly evidence loop)

**Status:** ACTIVE  
**Branch:** `cursor/pick-audit-harness-4988`  
**Owner:** Agent A (council / learning loop)

## Goal

Nightly **selection oracle**: was the published (or gated candidate) pick actually #1 at `timestamp_utc` under the locked universe policy?

**Not** outcome grading — resolver + judge postmortems handle that.

## Locked oracle policy

**Primary PASS gate:** `scheduler_cap_24`  
- `min(PICK_SCHEDULER_UNIVERSE_CAP, TOP_SCORING_UNIVERSE)` via `cap_subnets_for_scoring`
- Matches `internal/council/pick_scheduler.py` universe

**Secondary replay (diagnostics only):** `snapshot_cap_40`, `full_universe`

## Harness

| Piece | Location |
|-------|----------|
| Audit core | `internal/council/pick_selection_audit.py` |
| Worker scheduler | `internal/council/pick_audit_scheduler.py` |
| Artifact | `data/pick_audits/YYYY-MM-DD.json` |
| Manual / CI | `scripts/nightly_pick_audit.sh` (exit 2 on MISS) |

**Schedule:** `23:45 UTC` (`PICK_AUDIT_SLOT_UTC_HOUR/MINUTE`)

## Loop (evidence — not confidence)

1. Load today's `daily_picks.json` row
2. Replay `select_daily_pick` per policy (Python only)
3. `PASS` if `published_netuid == oracle.scheduler_cap_24.netuid`
4. `MISS` → classify + rule-based `questions` (what/why/rule/devil)

## Graph (routing after evidence)

| Verdict | Action |
|---------|--------|
| PASS | Log + optional Ditto STATUS |
| MISS + `universe_mismatch` | **Cursor Automation** — read audit JSON, draft PR (cap regen universe) |
| MISS + `stale_data` | Cursor or rule fix for boot HOLD |
| MISS + other | Human + `pick_explain` on both netuids |

## Cursor Automation recipe (create in Cursor UI)

**Name:** Pick audit MISS investigator  
**Trigger:** Manual, or scheduled after `nightly_pick_audit.sh` fails (exit 2), or webhook from worker log  
**Prompt:**

```text
Read data/pick_audits/<today UTC>.json from the subnet-dashboard repo.
If verdict is MISS and category is universe_mismatch or stale_data:
1. Summarize published vs oracle_scheduler_cap_24 from the JSON (do not re-score).
2. Trace code path that wrote daily_picks (get_or_create_today_pick callers).
3. Draft minimal PR with pytest proof; run tests/test_pick_selection_audit.py.
Do not guess scores — trust the audit artifact.
```

## AC

- [ ] `pytest tests/test_pick_selection_audit.py` green
- [ ] Worker starts `pick-selection-audit` job (`PICK_AUDIT_ENABLED=on`)
- [ ] `scripts/nightly_pick_audit.sh` writes JSON and exits 0 on PASS
- [ ] SN78 / 2026-07-27 class: `universe_mismatch` when published=78, oracle_scheduler=40 (fixture test)
- [ ] Ditto `save_memory` on MISS only (optional human step)

## NON-GOALS

- LLM nightly “was this the best pick?” chat loop
- Replacing resolver / judge postmortems
- Auto-merge PRs from automation

## DITTO

Post nightly: `STATUS pick-audit PASS|MISS category=… published=… oracle=… path=data/pick_audits/…`
