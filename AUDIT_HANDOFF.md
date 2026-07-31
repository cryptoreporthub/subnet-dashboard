# Audit handoff (2026-07-31) — find the *real* fix

**Repo tip:** `main` @ latest · Live: `https://subnet-dashboard.fly.dev`  
**Product:** FastAPI Subnet Dashboard + SimiVision

## Framing (important — do not rubber-stamp the rollback)

Agents rolled prod from **split_v2 → v1** because web→worker private HTTP failed and volume UIs stayed empty. That was **operational triage**, not proof that v1 is the correct architecture.

**Honest read:**
- We **upgraded to v2 for a real reason**: one machine doing HTTP + heavy background work was wedging `/health` and the site under load.
- We **downgraded because the switch failed**, not because the goal was wrong.
- Soft stubs, flycast/6PN thrash, and “local fallthrough” were **bandaids**. Rolling back to co-located volume is also a **bandaid** relative to the original goal — it restores data by abandoning load separation.
- **The true problem was never solved:** reliable volume ownership on a dedicated worker *plus* a reliable path for web to read that volume without wedging HTTP.

Claude’s job: propose and justify the **correct** long-term fix — not “keep v1 forever” and not “more proxy timeouts.”

## What “correct” must satisfy (acceptance)

1. **HTTP stays responsive** under resolver/pump/telegram/hydrate load (`/health` and homepage do not wedge for minutes).
2. **Volume-backed product data actually flows** — daily-pick, message-intel, mindmap/trail, learning/health, pump desk — real payloads, not `status: degraded` / empty stubs.
3. **Deploys are deterministic** — no CI force-flag that silently re-breaks networking; volume attach strategy is explicit and tested.
4. **One foundation** — still `server:app` only (no second server package).

If a design fails (1) or (2), it is not done.

## Why v2 was attempted (keep this)

```
Browser → web (HTTP only, no heavy jobs)
              ↓ private HTTP / shared storage?
         worker (owns data_volume + schedulers)
```

Intent: stop background CPU from starving uvicorn on a 2GB shared-cpu box.

## What actually broke on v2 (root causes to investigate)

Not “v2 is philosophically wrong” — the **implementation + Fly networking** failed:

| Failure | Symptom |
|---------|---------|
| Web had **no volume**; all volume GETs **proxied** to worker | When private hop died, entire product desk went empty |
| Private hop unreliable | 6PN connection refused, process DNS refused/NXDOMAIN, flycast flaky/intermittent |
| CI **forced** `fly.worker-v2.toml` + `FORCE_WORKER_SPLIT_V2` every deploy | Made a broken topology permanent |
| Soft-degraded JSON / fallthrough | UI stopped wedging on 503s but **lied** about having data |
| Peer/probe PRs (#698–#704) | Tuned timeouts and stubs; **did not** prove a stable data plane |

Learning/resolver could look “alive” on one probe and volume APIs still soft-fail the next — flaky, not fixed.

## Current state after rollback (#706–#708)

- Canon **in prod right now:** v1 — `fly.toml`, one web machine, `data_volume` + **inline worker**
- Data can load again when the VM is healthy
- **Known regression of the original pain:** single VM can still wedge (homepage/mindmap/pump under load) — deferred boots and skipping homepage warm are mitigations, not a structural fix
- Proxy code paths remain in-tree for opt-in v2 (`internal/worker_proxy.py`, `fly.worker-v2.toml`, enable/disable scripts)

## Design space Claude should evaluate (pick one, or a better hybrid)

### A. Make split_v2 actually work (honor the upgrade)
- Prove web→worker reachability (IPv6 6PN listen on `:8081`, service definition, no flycast-to-self)
- Health: worker process + volume mount + internal `/health` before web serves traffic
- Prefer **fail closed with retry** over soft-empty product APIs — or cache last-good volume snapshots on web with TTL honesty
- CI must **not** force v2 until a probe soak is green
- Document volume migrate: worker-only mount, never orphan web JSON disabling proxy

### B. Shared storage without HTTP proxy
- Same volume strategy Fly supports (or object store / LiteFS / rsync snapshot) so web reads files locally while worker writes
- Removes the private HTTP SPOF while keeping CPU split

### C. Bigger single machine / process priority (stay “one box” but fix wedging)
- Only acceptable if (1)+(2) above are proven under hydrate + resolver + pump
- e.g. dedicated CPU, stricter worker nice/cgroup, never block event loop on mindmap/homepage
- This is “fix v1 properly,” not “pretend v2’s goal was wrong”

### D. Edge/API split (Phase C in docs)
- Static/CDN front + API Fly — only if it addresses load without inventing a new broken hop

**Reject as “the fix”:** more soft `degraded` stubs, more fallthrough to empty local disk on web, more DNS/order thrash without a soak test.

## Repo map (for investigation)

| Area | Path |
|------|------|
| Deploy canon | `.github/workflows/fly.yml`, `fly.toml`, `fly.worker-v2.toml` |
| Enable/disable v2 | `scripts/fly_enable_worker_v2.sh`, `scripts/fly_disable_worker_v2.sh` |
| Proxy | `internal/worker_proxy.py`, `internal/worker_proxy_middleware.py` |
| Volume detect | `internal/data_volume.py` |
| Split docs | `docs/fly-web-worker-split.md` |
| Locks / runbook | `cursor-agents-communication/fly-worker-split-v2-lock.md`, `split-v2-rollback-runbook.md` |
| Contract | `tests/test_endpoint_contract.py` |

## Live smoke (secondary — flaky when wedged)

```bash
curl -sS -m 15 https://subnet-dashboard.fly.dev/health
curl -sS -m 20 https://subnet-dashboard.fly.dev/api/ops/live | jq '{worker_mode,worker_peer,volume}'
curl -sS -m 20 https://subnet-dashboard.fly.dev/api/daily-pick | jq '{status,action}'
curl -sS -m 20 'https://subnet-dashboard.fly.dev/api/message-intel?limit=2' | jq '{status,total:(.meta.total_messages)}'
```

## Deliverable asked of Claude

1. **Root-cause diagnosis** of why v2’s data plane failed (networking vs listen vs volume attach vs app bug).
2. **Recommended architecture** (A/B/C/D or better) with tradeoffs.
3. **Concrete implementation plan** (files, Fly config, probes, rollback gates) that meets acceptance (1)–(4).
4. What to **delete** (stub paths, force flags) so we stop shipping bandaids.

Do **not** conclude “rollback to v1 is the fix” unless you can show the original wedge problem is solved another way and load separation is unnecessary.
