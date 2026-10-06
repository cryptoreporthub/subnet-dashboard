# soul_map byte-size drift investigation (WS4)

**Pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129` (unchanged on prod `/version`)  
**Branch:** `cursor/audit-evidence-2026-10-05-smoke` (PR #1324)  
**Investigated:** 2026-10-06T03:37Z UTC  
**Conflict under review:** Ditto blind L2.3 `wc -c` **851,941 B** vs MC L2-PERSIST-HYDRATE bundle **854,356 B** (−2,415 B)

## Verdict

**`normal_write_activity`** — `conflicts_with` **resolved**.

The −2,415 B delta is a point-in-time comparison of the **live mutable** `data/soul_map.json` on the Fly volume between two L2.3 `wc -c` reads ~4h34m apart at the **same deploy pin**. It is not stale MC evidence, not a pin mismatch, and not evidence that the persist/hydrate hypothesis bundle is wrong. Byte size is expected to move as inline-worker resolver cycles, score snapshots, and mindmap trail/feedback writers mutate the blob.

## Live probes (required method 1)

| Probe UTC | Endpoint / method | Bytes | SHA-256 (body) | Pin match |
|---|---|---:|---|---|
| 2026-10-06T03:28:49Z | `GET /api/soul-map` (WS1) | 453,990 | — | yes (`/version`) |
| 2026-10-06T03:37:10Z | `GET /api/soul-map` (WS4) | 455,994 | `f5651afbbc76bbfde4d239fae4496eeab61a2c079372a0520427fd95109b3392` | yes |
| 2026-10-06T03:29Z | L2.3 `wc -c /app/data/soul_map.json` (blind) | 851,941 | — | yes |
| ~2026-10-05T22:55Z | L2.3 `wc -c` (MC bundle) | 854,356 | — | yes |

Receipts: [`ws1-live-probes-2026-10-06T03:28:49Z.txt`](ws1-live-probes-2026-10-06T03:28:49Z.txt), [`ws4-soul-map-live-probes-2026-10-06T03:37:10Z.txt`](ws4-soul-map-live-probes-2026-10-06T03:37:10Z.txt).

### Metric distinction (root cause of apparent “conflict”)

| Layer | Serialization | Typical size @ pin |
|---|---|---:|
| **Volume** (`wc -c` on `/app/data/soul_map.json`) | `json.dump(..., indent=2)` via `write_soul_map` | ~852 KB |
| **HTTP** (`GET /api/soul-map`) | FastAPI compact JSON wrapper `{"status","data"}` | ~454 KB |

At WS4 probe time, recomputing `indent=2` from the live API `data` payload yields **854,523 B** (ratio compact→indent ≈ **1.8703×**). That sits between MC (**854,356**) and blind (**851,941**), confirming all three volume readings are the same on-disk format with normal hourly drift.

WS1 → WS4 API growth: **+2,004 B** in ~8m21s (+0.44%). MC → blind volume shrink: **−2,415 B** in ~4h34m (−0.28%). Both magnitudes are consistent with continuous writer activity, not contradictory evidence.

## Static trace @ pin (required method 2)

All disk writes funnel through `internal/store/soul_map_io.py:write_soul_map` → `fcntl.flock` (≤5s) → `json.dump(blob, indent=2)` → `os.replace` (atomic). Deploy pin does **not** gate runtime mutations; only code path changes do.

**Writers at `ce3d8200` (grep `write_soul_map` / `_save_raw`):**

| Module | Trigger | Size impact without pin change |
|---|---|---|
| `resolver_scheduler.py:735,1176` | Resolver lifecycle + cycle summary/history | Updates timestamps, `cycle_history` (capped `CYCLE_HISTORY_MAX=10`) |
| `mindmap_bridge.py` | Learning trail, feedback logs, selector output | `learning_trail[-200:]`, `feedback_logs[-10:]` — append+trim can **net shrink** when large entries roll off |
| `weights.py` / `formula_versions.py` | Council/signal weight learning | Float rounding, `formula_versions.history[-20:]` |
| `indicator_scheduler.py`, `scheduler.py`, `simivision/engine.py`, `judges/weights.py`, `liveness.py` | Scheduled / pick / judge side-effects | Section-local mutations, full re-serialize |
| `rotation_tokens.py` | Rotation snapshot mirror | Token list content/size varies |
| `scripts/compact_soul_map.py` | Manual compaction (not scheduled) | Would shrink; not observed in window |

**Largest on-disk key (live WS4):** `feedback_logs` ≈ 451 KB indent2 — dominates byte budget; capped at 10 entries so replacement/removal of a large log row can move total size by kilobytes in one write.

**Hydration path:** `server.py:2296-2300` reads file via `load_data` (no transform); does not write. Hydrate/persist wedge hypothesis is unaffected by size drift.

## Cross-check (required method 3)

| Source | Finding | Consistent with verdict? |
|---|---|---|
| [`L2-PERSIST-HYDRATE-001.json`](../findings/L2-PERSIST-HYDRATE-001.json) | 854,356 B volume @ MC audit; flock ≤5s PLAUSIBLE | Yes — MC timestamp earlier; size still ~852 KB band |
| [`ditto-blind-l1l2-results.md`](../ledger/ditto-blind-l1l2-results.md) | 851,941 B @ 03:29Z; flagged `conflicts_with` | Yes — later read, same metric, normal drift |
| [`ws1-live-probes` receipt](ws1-live-probes-2026-10-06T03:28:49Z.txt) | API 453,990 B; pin match; responsive 0.384s | Yes — compact layer; ×1.87 ≈ blind volume |
| [`open-questions-closure.md`](../ledger/open-questions-closure.md) O3 | Prior Ditto probe ~840 KB refutes 24 MB bloat | Yes — same ~850 KB band, not contradiction |

## Bounded unknown (explicit)

- No fresh L2.3 `wc -c` in this VM (`flyctl` unavailable); volume sizes for MC/blind taken from prior receipts. Live API + indent2 recompute bounds current volume to **~854.5 KB** at 03:37Z.
- Per-write attribution of the exact −2,415 B (which key/trim) is **NOT_OBSERVABLE** without Fly log correlation or write-audit instrumentation.

## Recommendation

- Treat soul_map **byte count as a live gauge**, not a pin-stable artifact, in L2 bundles.
- L2-PERSIST-HYDRATE bundle: add `soul_map_size_observability: LIVE_MUTABLE` note; retain 854,356 B as MC audit-time snapshot with timestamp.
