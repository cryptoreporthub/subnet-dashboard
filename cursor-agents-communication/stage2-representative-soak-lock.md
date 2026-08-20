# Stage 2 representative soak — LOCK

**Status:** **READY TO RUN** (infra merged; human triggers deploy + GHA)  
**Blocks:** Stage 3 cutover retry until this soak passes with instrumentation artifacts  
**Prior agent:** bc-01a019c1 — alive-flip investigation (2026-08-20)

## Finding (why hop soak is insufficient)

Stage 2 soak #5 (`STAGE2_HOP=1`, no volume, `WORKER_HEAVY=off`, schedulers skipped) proves **flycast networking only**. It does **not** exercise the worker process that died in Stage 3 hold: essential schedulers + volume + Telegram flags on `shared-cpu-1x` 2GB.

## WORKER_HEAVY decision (explicit)

| Mode | Stage 2b soak | Stage 3 cutover | Notes |
|------|---------------|-----------------|-------|
| **essential** | **YES** | **YES** | Pump/resolver/whale/registry/Telegram deferred boot — no live-subnet wedge |
| **full** | **NO** | **NO** | Wedges 2GB VM (#517/#520); DEPLOY.md forbids on current Fly sizing |

`fly.worker-v2-essential-soak.toml` sets `WORKER_HEAVY=essential`. Do not bump to `full` without a larger worker VM and a new capacity review.

## Runbook

### 0. v1 baseline must be green first

```bash
./scripts/fly_v1_freshness_gate.sh
```

**Read the output, not just exit code.** A green gate rules out the buried “v1 baseline capacity” concern from the alive-flip report. A fail (degraded learning-health, daily-pick 90s timeout, resolver not running, `subnet_sync_last_ok=0`, live_subnets boot timeout) is a **live prod problem** — fix or recover v1 before representative soak or Stage 3. Do not treat fail as “expected, move on.”

Do not start representative soak or Stage 3 while v1 shows stale freshness / missed scheduler ticks.

### 1. tmp boot reaper (volume orphans)

```bash
./scripts/fly_tmp_boot_reaper.sh
# dry-run: TMP_BOOT_REAP_DRY=1 ./scripts/fly_tmp_boot_reaper.sh
```

Also runs automatically at worker boot (`internal/tmp_boot_reaper.py`).

### 2. Deploy representative topology

```bash
./scripts/fly_stage2_representative_worker.sh
```

- Migrates `data_volume` web → worker
- `STAGE2_REPRESENTATIVE=1`, real schedulers, `MESSAGE_INTEL_LISTENER=auto`
- **Does not** set `WORKER_SPLIT_V2=on`

### 3. Soak with instrumentation (GHA)

Workflow: **Fly Stage 2 representative soak**  
Inputs: `confirm=soak-representative`, optional `soak_hours` (default 4)

Artifacts:
- `stage2_soak_*.log` — zero-failure probe log
- `soak_samples.jsonl` — per-probe health latency, RSS/CPU, metrics snip

Post-soak: run `scripts/fly_stage2_probe_metrics.sh` with **human org token** for Prometheus CPU/mem series.

### 4. Rollback to v1

```bash
./scripts/fly_stage2_representative_rollback.sh
```

## Gate to Stage 3

All required before `fly_enable_worker_v2.sh`:

1. Representative soak **SOAK PASSED** (validate via `scripts/validate_stage2_soak_log.py`)
2. `soak_samples.jsonl` shows stable worker flycast latency + no RSS runaway
3. v1 freshness gate green **after** rollback recovery window
4. Human review of v1 baseline capacity (scheduler timeouts on v1 = prod problem, not Stage 3-only)
