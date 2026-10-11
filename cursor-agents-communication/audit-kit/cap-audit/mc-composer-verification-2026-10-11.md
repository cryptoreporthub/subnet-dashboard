---
cursor:
  subagentId: "bc-a0716939-8693-5bfe-be85-83569391a85b"
---

# MC Composer verification — cap-audit code claims

**Verified pin:** `main` @ `dd195788b3222370be8834a8e2b6cee1cf877524` (fetched 2026-10-11).

**Method:** Read-only source inspection at pin; no pytest run.

**Universe note (for coverage claims):** Provider/display feeds can exceed active membership (handoff cites ~166 `/api/subnets` rows vs ~129 provider-labelled active including Root, ~128 non-root tradable). `tradable_subnets()` only drops Root/invalid; it does not prove chain-active membership.

**Score snapshot module path:** `internal/council/score_snapshots.py` (not under `internal/learning/`).

---

## Claim verdicts (Claude first-pass code findings)

| # | Claim (summary) | Verdict | Evidence |
|---|-----------------|---------|----------|
| 1 | Snapshot `count` is `len(rows)` after `tradable_subnets()`, not successful scores; tick can report `ok: True` when `save_score_snapshot` skips older publish | **CONFIRMED** | `build_full_universe_snapshot`: `rows = tradable_subnets(subnets)` (`score_snapshots.py:240`), `"count": len(rows)` (`286`); per-netuid scoring uses `except Exception: pass` (`261-262`, `273-274`). `write_full_universe_snapshot` → `_build_and_save` always returns `{"ok": True, "count": payload.get("count"), ...}` after `save_score_snapshot(payload)` (`348-361`). `save_score_snapshot` can `return` without writing when incoming stamp is older (`154-167`). |
| 2 | Failures swallowed: `except Exception: pass` on scoring; bad netuid dropped with `continue` | **CONFIRMED** | Hour/day score loops: `except Exception: pass` (`score_snapshots.py:261-262`, `273-274`). Invalid netuid: `except (TypeError, ValueError): continue` (`247-249`). Related hot-path pattern (not snapshot): `score_cache.score_universe` `except Exception: continue` (`score_cache.py:76-77`). |
| 3 | `progress_cb` rewrites `soul_map.json` every 20 subnets; `fly.toml` ties ~101s soul_map RMW to resolver wedges | **PARTIAL** | Every 20 scored rows: `if progress_cb and total and (idx + 1) % 20 == 0` (`score_snapshots.py:275-276`). Scheduler wires `progress_cb=_progress` (`683`), and `_progress` calls `_persist_cycle_summary` (`671-678`), which loads/saves full `soul_map` via `weights._load_raw` / `_save_raw` (`715-735`). **Not** every `progress_cb` call site does soul_map RMW (only scheduler path). `fly.toml:47` documents resolver cycle bump due to `~101s persist_summary_rmw` (resolver scheduler), not score-snapshot progress — same shared `soul_map.json` contention, different writer. |
| 4 | Snapshot cap via `_cap_subnets_for_scoring` rank-based (`MEGA_CEILING_RANK=10`, mid `11-75`); raising cap alone does not yield full-active on background path without bypassing selector | **PARTIAL** | When `len(subnets) <= cap`, `cap_subnets_for_scoring` returns the list as-is (`scoring_cap.py` early return). When `_snapshot_subnet_cap()` is `0`, worker skips `_cap_subnets_for_scoring` (`score_snapshots.py:333-337` `if cap > 0`). **Bypassing the rank selector is sufficient for full membership on that path, not strictly necessary** if cap is unset/zero or `cap >= len(membership)`. When `cap > 0` and `len > cap`, rank/heuristic selection applies (`scoring_cap.py:91-121`; Fly `SCORE_SNAPSHOT_MAX_SUBNETS=40`). Claude’s “must bypass” overstates the only path. |
| 5 | Pick scheduler effective cap `min(24, TOP_SCORING_UNIVERSE=20)`; feeds A/B benchmark | **CONFIRMED** | `PICK_SCHEDULER_UNIVERSE_CAP` default 24 (`pick_scheduler.py:32`). `_load_capped_subnets`: `cap = min(PICK_SCHEDULER_UNIVERSE_CAP, TOP_SCORING_UNIVERSE)` (`157-158`). `server.py` `TOP_SCORING_UNIVERSE` default **20** (`630`). On successful daily tick, `_record_ab_benchmark(subnets, ctx, "daily-pick-scheduler")` (`364-366`); hour tick same (`484-486`). With defaults, capped list size ≤ 20. |
| 6 | 90s daily-pick tick timeout → `scheduler_hold` on timeout; rescoring ~129 subnets risky | **PARTIAL** | `DAILY_PICK_TICK_TIMEOUT_SECONDS` default **90** (`pick_scheduler.py:35`). Timeout sets `result["error"]` (`351-352`); when `not today_ready and result.get("error")`, `write_scheduler_hold` (`372-377`). **129 risky:** not a code constant; inference from ~128 tradable + Root display vs 90s budget (snapshot write timeout **480s** in `fly.toml:83`, **600** code default `score_snapshots.py:33-35`). Timeout << full-universe scoring cost — risk statement **plausible, not encoded**. |
| 7 | Hidden 75 limits: emergency registry 0-74, live cache ~75 rows, mid-rank max 75, `MAX_NETUIDS=200` | **PARTIAL** | **Mid-rank 75:** `SCORING_CAP_MID_RANK_MAX` default 75 (`scoring_cap.py:113`; `fly.toml:86`). **`MAX_NETUIDS=200`:** `chain_client.py:34`, `subnet_universe.py:20`; `get_all_netuids` uses `min(total, MAX_NETUIDS)` (`chain_client.py:274`, `284`). **Emergency registry 0-74:** docstring only (`subnet_universe.py:450`); `emergency_registry` loads `_emergency_rows()` with **no** `range(75)` slice (`468-472`) — count follows committed registry size (not present in this checkout). **Live ~75:** comment in `subnet_universe.py:94-95` and `fly.toml:55-57` (75-subnet batch / clipped cache); no literal `75` row cap in `live_subnets.py` — partial fetches under `LIVE_SUBNETS_BATCH_DEADLINE_SECONDS` (`chain_client.py:578-594`). |
| 8 | Tiny snapshot input with `REGISTRY_ONLY` → registry fallback → 3-row static fallback; denominator should be universe snapshot not loaded list | **PARTIAL** | `_registry_only_snapshot()` default on worker (`score_snapshots.py:292-303`). `write_full_universe_snapshot` uses `_get_subnets_hydrate()` when registry-only (`327-328`). Hydrate: `load_subnets_for_display` then `tradable_subnets`; else `tradable_subnets(_STATIC_SUBNETS)` **3 rows** (`server.py:2590-2604`, `_STATIC_SUBNETS` `2560-2570`). `count` / `total` use post-cap **loaded** list (`len(subnets or [])` log `343`, `len(rows)` in payload `286`) — not `subnet_universe` snapshot cardinality. Normative “denominator must be universe snapshot” is **engineering recommendation**, not current behavior. |

---

## Handoff doc cross-check (`cursor-cap-audit-handoff.md`)

| Handoff statement | vs pin `dd195788` |
|-------------------|-------------------|
| P0 defaults (TOP 20/40, scheduler 24, `SCORE_SNAPSHOT_MAX_SUBNETS=40`, timeouts 480/90) | **CONFIRMED** in source + `fly.toml` (`60`, `82-83`). |
| Priority #3 “count=len(**inputs**)” | **REFUTED** wording — code uses `len(rows)` after `tradable_subnets` (`score_snapshots.py:240`, `286`), semantically “inputs to score loop” not raw feed length. |
| Priority #4 prior-snapshot rank slice | **CONFIRMED** (`scoring_cap.py:102-107`). |

---

## Extra pins requested

| Symbol | Web / `server.py` | Engine / worker paths |
|--------|-------------------|------------------------|
| `TOP_SCORING_UNIVERSE` | default **20** (`server.py:630`) | default **40** (`daily_pick_engine.py:210`, `pick_selection_audit.py:58`, `score_snapshots.py:52` worker `_snapshot_subnet_cap`) |
| `SCORE_SNAPSHOT_MAX_SUBNETS` | `int(os.environ.get(..., "0"))` (`score_snapshots.py:36`); **Fly declares 40** (`fly.toml:82`) | same env; worker uses cap when `> 0` (`333-337`) |
| `LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS` | code default **60** (`live_subnets.py:53`) | **Fly override 90** (`fly.toml:60`) |

---

## `/api/daily-pick/weighed`

**Exists** at `server.py:3161-3180`. Uses `_get_subnets_with_source` / hydrate fallback, then `_cap_subnets_for_scoring(subnets)` with server default limit path (`3132-3148`, `_cap_subnets_for_scoring` delegates to `TOP_SCORING_UNIVERSE` `server.py:908-915`).

---

## Claude “did not open” files — contradiction check

| File | Contradicts Claude? |
|------|---------------------|
| `internal/subnets/scoring_cap.py` | **No** — confirms rank/heuristic cap and mega/mid ranks. |
| `internal/council/score_cache.py` | **No** — adds API-path `continue` on score errors (`76-77`); aligns with swallowed-failure theme. |
| `internal/subnets/tradable.py` | **No** — confirms Root exclusion only, no active-membership filter (`28-31`, `43-51`). |
| `internal/council/pick_score_cache.py` | **No** — cache sizing/TTL; documents 20-subnet steady state (`12-13`), consistent with small-universe caps. |
| `source-cap-register.csv` | **Not re-derived** at this SHA (inventory pinned to `9535c3c2…` in handoff); no line-level contradiction attempted. |

Council-heavy modules (resolver, `daily_pick.py`, etc.) were not exhaustively re-audited here; nothing above **refutes** the eight code claims.

---

## Summary counts

| Verdict | Count |
|---------|------:|
| CONFIRMED | 3 |
| PARTIAL | 5 |
| REFUTED | 0 |
| UNVERIFIED | 0 |

*(Handoff-only wording “len(inputs)” would be **REFUTED** if counted as a ninth claim; table above uses Claude’s eight findings.)*
