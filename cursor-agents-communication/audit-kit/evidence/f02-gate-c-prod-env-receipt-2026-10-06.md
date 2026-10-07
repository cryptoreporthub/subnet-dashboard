# F02 Gate C prod env receipt — F02 q12

| Field | Value |
|---|---|
| Status | **COMPLETE** (read-only; no fresh prod probe on this run) |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Receipt date | 2026-10-06T20:05Z |
| Executor | MC worker `bc-c00c677f-a9f1-5cf3-9bc3-f36c5f5199fe` |
| Audit anchor | [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Gate C grant | Joshua 2026-10-06 (Tracks 1–3; read-only prod SSH/console) — see [`phase3-track2-gate-c-scope.md`](phase3-track2-gate-c-scope.md) |

**Scope:** F02 §2b q12 — effective production environment for F02-relevant knobs. This receipt consolidates the **L2.3 machine-exec env read** already executed during audit blind parallel (2026-10-06T03:29Z). No new `fly ssh` / `fly machine exec` on this MC turn (`flyctl` unavailable on cloud agent VM).

---

## Effective production env (L2.3 machine exec, 2026-10-06T03:29Z)

Source: [`ledger/ditto-blind-l1l2-results.md`](../ledger/ditto-blind-l1l2-results.md) → L2-PERSIST-HYDRATE-001.

| Variable | Observed value | Code default (if silent) | F02 relevance |
|---|---|---|---|
| `WORKER_HEAVY` | `essential` | `essential` (`fly.toml:40`) | Skips live_subnets sync; essential schedulers only |
| `INLINE_WORKER` | `1` | `1` | Inline worker on web machine |
| `ENABLE_INLINE_WORKER` | `1` | `1` | Enables inline worker boot path |
| `HYDRATE_SUBNETS_TIMEOUT_SECONDS` | `4` | `4` (`fly.toml:53`) | Subnet hydrate budget |
| `RESOLVER_CYCLE_TIMEOUT_SECONDS` | `360` | `120` (module default) | **Committed fly.toml override active in prod** — matches `fly.toml:48` |
| `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS` | `480` | `480` (typical) | Write timeout vs stuck threshold (O16) |

## Silent / code-default knobs (NOT read on L2.3)

Per [`ledger/candidate-matrix.md`](../ledger/candidate-matrix.md) ENV rows — effective runtime **NOT_OBSERVABLE** on this receipt:

| Variable | `fly.toml` | Code default | Notes |
|---|---|---|---|
| `LOOP_STALL_GUARD_KILL` | *(silent)* | `True` | Enables `os._exit(1)` path when guard fires |
| `LOOP_STALL_GUARD_ENABLED` | *(silent)* | `True` | Guard started when background boot runs |
| `RESOLVER_FIRST_TICK_TIMEOUT_SECONDS` | *(silent)* | `min(360, 90)=90` at module | First-tick cap may differ from cycle cap |
| `RESOLVER_REFRESH_MINUTES` | `15` | `15` | Declared in fly.toml; runtime use assumed match |

## Committed vs observed

| Knob | `fly.toml` committed | L2.3 observed | Match |
|---|---|---|---|
| `RESOLVER_CYCLE_TIMEOUT_SECONDS` | `360` | `360` | **YES** |
| `WORKER_HEAVY` | `essential` | `essential` | **YES** |
| `HYDRATE_SUBNETS_TIMEOUT_SECONDS` | `4` | `4` | **YES** |

Resolves open-questions **O16** partial boundary: committed 360s is **confirmed effective** in prod at L2.3 read time. `LOOP_STALL_GUARD_KILL` effective value remains **NOT_OBSERVABLE** (silent in fly.toml; code default True).

---

## Verdict

**PARTIAL PASS (Gate C env inventory).** Six F02-critical vars read on production machine exec; committed `RESOLVER_CYCLE_TIMEOUT_SECONDS=360` confirmed effective. Silent guard knobs not re-probed on this turn.

**NOT CLAIMED:** post-03:29Z env drift, secrets values, multi-machine env parity, restart-after-read side effects.

**Fences honored:** no deploy, restart, secrets set/unset, or volume mutation.
