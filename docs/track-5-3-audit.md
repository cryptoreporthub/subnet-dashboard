# Track 5.3 Audit

Pin: `c9449d6490231373748f19f299ed19d423a1c971` (`c9449d64`).

Status: verified on the pin. Live config values are from GitHub Actions run `35656500026` (keyed extraction only). This note does not change product behavior.

## Blob identity

| Path | Git blob SHA | Bytes |
| --- | --- | --- |
| `internal/subnets/scoring_cap.py` | `849d78f8ed51239878ac5184acf5c3e995d0f756` | 3601 |
| `internal/background_boot.py` | `346250dba19900d5058f25af019253942d3664c4` | 24159 |
| `internal/council/resolver_scheduler.py` | `82f8954db2903090688e619d43a543ff81ebd228` | 57275 |

## Resolver scheduler starvation loop

`resolver_scheduler.py` builds a fresh single-worker pool for each cycle (`ThreadPoolExecutor(max_workers=1)` around lines 822–907).

On `FuturesTimeoutError`, `_abandon_inflight_cycle` increments `_cycle_generation` and releases the cycle lock (lines 737–761, called from 862–865). The in-flight function is not joined. The pool is shut down with `wait=False` and `cancel_futures=True` (line 907), so the orphan thread keeps running.

The busy path (`heavy_job_busy`, line 615) and the timeout path (lines 649–651) both reschedule with `min(2, max(1, self.refresh_minutes))`, which is 1–2 minutes. A cycle that outlives its timeout therefore continues while the scheduler starts another attempt on that short interval. The audit reads cycles that run longer than 10 minutes as staying in that spin until the orphan finishes or the process restarts.

## `defer_boot`

`defer_boot` in `internal/background_boot.py` lines 34–46 starts one daemon thread. It sleeps, calls the target once, and logs a failure. There is no retry loop. A service that fails in that call stays down until the process restarts.

## Live config

GitHub Actions run `35656500026` (`minutes=0`, keyed step only) printed:

```text
SCORE_SNAPSHOT_MAX_SUBNETS= 40
WORKER_HEAVY= essential
```

`SCORE_SNAPSHOT_MAX_SUBNETS=40` is the production override of the code default `0`. `WORKER_HEAVY=essential` is the live value for F-1b.
