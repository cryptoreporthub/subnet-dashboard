# Ditto blind parallel L1+L2 results

**Verifier:** Ditto blind parallel (workstream 4/5)  
**Pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129`  
**Branch:** `cursor/audit-evidence-2026-10-05-smoke` (PR #1324)  
**Verified at:** 2026-10-06T03:30Z UTC  
**Method:** Independent re-derive per `DITTO-TICKET-L1L2.md` — MC bundles **not** read before verification.

---

## Per-claim verdict table

| claim_id | lane | class | verdict | disposition (blind) | conflicts_with MC |
|---|---|---|---|---|---|
| SMOKE-001 | 1 | C5 | **PASS** | CONFIRMED | — |
| SMOKE-002 | 1 | C8 | **PASS** | CONFIRMED | — |
| C6-WORKER-HEAVY-ESSENTIAL-001 | 1 | C6 | **PASS** | BY-DESIGN | — |
| L2-INC-A-001 | 2 | L2-INC-A | **PASS** | UNKNOWN | — |
| L2-INC-B-001 | 2 | L2-INC-B | **PASS** | UNKNOWN | — |
| L2-INC-C-001 | 2 | L2-INC-C | **PASS** (audit-time) / **UNVERIFIED** (incident-time 11:49:15Z) | UNKNOWN | — |
| L2-PERSIST-HYDRATE-001 | 2 | L2-persist-hydrate | **UNVERIFIED** (hypothesis) / **PASS** (code + env partial) | UNKNOWN | ~~`soul_map.json` byte count~~ **resolved** (WS4) |

**Summary:** 7/7 anchor claims independently re-derived. Lane 1: 3/3 PASS (byte-exact). Lane 2: 3/3 partial-receipt PASS on correlation evidence; 1 UNVERIFIED on causation hypothesis; 1 `conflicts_with` on live soul_map size drift.

---

## SMOKE-001 — StaticFiles mount

**Verdict:** PASS  
**fetch_method:** `git show ce3d820013d45577333ac8aada8c0d9e97c54129:server.py | nl -ba | sed -n '510,512p'`

```
   510	_static_dir = os.path.join(BASE_DIR, "static")
   511	if os.path.isdir(_static_dir):
   512	    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
```

**sha256 (lines 510–512):** `8e558d01852b2874cc88690e164c12ec0e4f6c6011d51c8c8cccf61b7cd64634`

---

## SMOKE-002 — write_soul_map swallow

**Verdict:** PASS  
**fetch_method:** `git show ce3d820013d45577333ac8aada8c0d9e97c54129:internal/council/resolver_scheduler.py | nl -ba | sed -n '735,737p'`

```
   735	            write_soul_map(_mutator, self.soul_map_path)
   736	        except Exception:
   737	            pass
```

**sha256 (lines 735–737):** `b3ec6478f0250df3b004df11c7af675a753e9b3051c0c76903c03ea810f497a0`

---

## C6-WORKER-HEAVY-ESSENTIAL-001 — essential gating

**Verdict:** PASS  
**fetch_method (three spans):**

1. `fly.toml:40` — `WORKER_HEAVY = "essential"`
2. `internal/run_mode.py:71-74` — `worker_heavy_feeds_enabled()` returns True only for `full`/`1`/`true`/`yes`/`on`; default `essential` → False
3. `internal/background_boot.py:552-556` — early return when `not heavy` (essential skips live_subnets)

**refutes_if check:** `worker_heavy_feeds_enabled()` does **not** return True under `essential`; `background_boot` returns before live_subnets bootstrap.

---

## L2-INC-A-001 — Incident A 08:29–08:55Z

**Verdict:** PASS (partial receipt; disposition UNKNOWN)  
**Window:** 2026-10-05T08:29:00Z – 2026-10-05T08:55:00Z

| Evidence class | Blind observation |
|---|---|
| GHA uptime run | Run `37283988892` created `2026-10-05T08:29:52Z`, conclusion `failure`. Log lines: `08:43:36Z curl: (28) Operation timed out after 20002ms`; `health_http=000000`; `live_http=000000`; `home_http=000000`; `ALL_OK=0` |
| Machine lifecycle | Fly GraphQL `machine(machineId:7841024b3712e8)` events: last start before window `2026-10-04T22:31:36Z`; next exit `2026-10-05T09:43:31Z` — **no exit/restart inside 08:29–08:55Z** |
| Fly app logs | Buffer earliest `2026-10-06T03:16:11Z` — incident window **NOT_OBSERVABLE** via `flyctl logs` |

**Mechanism:** UNKNOWN (service recovery NOT_OBSERVABLE; GHA timeout + no machine recycle correlation only).

---

## L2-INC-B-001 — Incident B 11:41:30–11:47:23Z

**Verdict:** PASS (partial receipt; disposition UNKNOWN)  
**Window:** 2026-10-05T11:41:30Z – 2026-10-05T11:47:23Z

| Evidence class | Blind observation |
|---|---|
| Machine lifecycle | GraphQL events: `2026-10-05T11:45:48Z exit`; `2026-10-05T11:45:48Z restart`; `2026-10-05T11:45:51Z start` — inside window |
| GHA uptime | Four runs on 2026-10-05: `01:55Z` success, `08:29Z` failure, `17:20Z` success, `23:13Z` success — **no run during 11:41–11:47Z** |
| Fly app logs | Buffer does not cover 11:41–11:47Z — **NOT_OBSERVABLE** |

**Mechanism:** UNKNOWN (lifecycle exit/restart timing only; cannot corroborate "48 consecutive probe timeouts" via GHA).

---

## L2-INC-C-001 — Static-asset wedge 11:49:15Z

**Verdict:** PASS (audit-time probes) / UNVERIFIED (incident-time 11:49:15Z)  
**Disposition:** UNKNOWN

| Evidence class | Blind observation |
|---|---|
| Machine lifecycle | Restart `11:45:48Z`, start `11:45:51Z` — Incident C at `11:49:15Z` is ~3m24s post-recycle |
| Audit-time L2.1 (2026-10-06T03:29Z) | Six parallel static GETs all HTTP 200: favicon 607B, smoke-tokens 6430B, base 9469B, ui 503871B, tribunal 1609B, cockpit_hydrate 235293B; parallel wall ~0.56s |
| Pin vs live byte-exact | `base.css`, `ui.css`, `tribunal-hero-layout.css` — **BYTE-EXACT MATCH** (pin blob SHA = live SHA) |
| Incident-time 11:49:15Z | No log replay — **NOT_OBSERVABLE** |

**Queuing-starvation mechanism:** REFUTED at audit-time (all static assets 200, sub-second); incident-time failure NOT_OBSERVABLE.

---

## L2-PERSIST-HYDRATE-001 — persist/hydrate hypothesis

**Verdict:** UNVERIFIED (causation hypothesis) / PASS (pin code paths + L2.3 env partial)  
**Disposition:** UNKNOWN

| Evidence class | Blind observation |
|---|---|
| Pin code | `internal/store/soul_map_io.py:47-65` — `fcntl.flock` with `timeout_seconds=5.0` default; `resolver_scheduler.py:735-737` bare swallow on persist failure |
| L2.3 machine exec env | `WORKER_HEAVY=essential`, `INLINE_WORKER=1`, `ENABLE_INLINE_WORKER=1`, `HYDRATE_SUBNETS_TIMEOUT_SECONDS=4`, `RESOLVER_CYCLE_TIMEOUT_SECONDS=360`, `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS=480` |
| soul_map.json size | `wc -c` → **851941 bytes** (2026-10-06T03:29Z) |
| Incident-window persist timings | Fly log buffer earliest `2026-10-06T03:16Z` — **NOT_OBSERVABLE** for 08:29–08:55Z or 11:41–11:47Z |

**conflicts_with MC (original):** MC bundle cites `854356 bytes` at audit time (~2026-10-05T22:55Z); blind L2.3 read `851941 bytes` (−2415 B) at 2026-10-06T03:29Z.

**WS4 resolution (2026-10-06):** `conflicts_with` **resolved** as `normal_write_activity`. Volume `wc -c` measures indent=2 on-disk serialization; deploy pin unchanged; ~0.28% drift over 4h34m within expected resolver/trail/feedback writer churn. Live API at 03:37Z: 455,994 B compact (sha256 `f5651afb…`); indent2 estimate 854,523 B — bracketing both prior volume reads. Receipt: [`evidence/soul-map-drift-investigation-2026-10-06.md`](../evidence/soul-map-drift-investigation-2026-10-06.md).

**Causation hypothesis** (persist/hydrate blocks ASGI during Incidents A–C): UNVERIFIED — lifecycle timestamps are correlation only.

---

## Blind verifier notes

- MC evidence bundles in `findings/*.json` were **not** consulted before independent checks.
- Fly GraphQL API used for machine lifecycle (250 events; 63 on 2026-10-05); `flyctl` v0.4.112 installed for logs/exec.
- GHA logs fetched via `gh run view 37283988892 --log`.
- Ditto does not write `ledger/claims.json`; overlaps flagged above only.
