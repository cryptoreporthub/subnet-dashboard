# §17 — Beyond the trust gap (features · UI · signals)

**Status:** DRAFT 2026-07-15 · fills what Ditto **purposely left out of §16** · **do not implement until §16 is done + this plan approved**  
**Depends on:** §16 Complete (`gameplan-phase-16.md`) — trust numbers honest before new surface area  
**Not:** a second trust-gap pass. This is growth after the ledger is trustworthy.

## Why this exists

§16 is intentionally narrow: fill blanks → gated `hybrid_score` → re-measure. Ditto excluded three buckets so §16 stays shippable. This document is the **final-plan home** for those buckets so the master plan is complete without bloating §16.

| Bucket | Intent |
|--------|--------|
| **Extra signals** | Stronger, signal-derived inputs — not more decorative gauges |
| **UI redesign / experience** | Predictive framing + unfinished polish — not a greenfield cockpit rewrite |
| **Big features** | Use the FastAPI foundation for chat/streaming and launch polish humans still owe |

## Sequencing

```
§16 trust gap  →  §17.S signals (unlocks real magnitude)  →  §17.U UI  ∥  §17.F features
```

- **Do not start §17 before §16 merges** (or an explicit gate-clear).
- Prefer **§17.S before heavy UI/feature polish** when work would display new scores — same “honest numbers first” rule as J→H.
- §17.U and §17.F may run in parallel once §17.S1 (signal-derived magnitude) is either shipped or explicitly deferred with a written note.

## Agent ownership

| Track | Primary | Secondary |
|-------|---------|-------------|
| **§17.S** Extra signals | A (`internal/council/*`, learning) + B (`internal/oracle/*`, indicators, whales) | Split by existing matrix |
| **§17.U** UI | B (`templates/*`, `static/*`) | A only if cockpit data contracts change |
| **§17.F** Big features | A (chat/streaming/routes) + B (templates) + **Human** (DNS/creds) | |

**Conflict surface:** `server.py` includes + `tests/test_endpoint_contract.py` only.

## Models

| Work | Model |
|------|-------|
| Lock slice contracts / magnitude design | Grok slow + **medium** (escalate **high** only if needed) |
| Implement | Composer 2.5 |
| Visual/UX redesign passes | Grok slow + medium design → Composer → medium sign-off |

---

## §17.S — Extra signals

**Goal:** Feed the council with *real* magnitude and richer optional channels — without inventing fake conviction.

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **S1** | A (+ B design note) | **Signal-derived `predicted_pct`** — replace confidence-proxy `_predicted_pct_from_pick()` with magnitude from state_vector / impact / oracle agreement (SciWeave unlock for true Phase-2 hybrid beyond §16’s gated stub) | New predictions store non-proxy magnitude; hybrid consumers can use real calibration; test proves proxy path gone for new rows |
| **S2** | B | **Whale / rugger / indicator signal depth** — thin routers already on CONTRACT; make payloads useful or honest-empty (no decorative zeros) | Existing `/api/whales/*`, ruggers, indicators return real summaries or explicit empty; one check per family |
| **S3** | A | **Optional social adapters** — Discord and/or X beside Telegram (Phase M leftover); env-gated, same dedup bus as message-intel | Feature-flagged; prod stays healthy with adapters off; no spam into council without review |

**Out of S:** New judge personas, threshold gaming, parallel Signal Hub rewrite (old Phase O hub already on `main`).

---

## §17.U — UI redesign / experience

**Goal:** Finish predictive-app polish and CONDITIONAL leftovers — not a second H-full rebuild.

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **U1** | B | **UI Phase 2 CONDITIONALs** — contrast (`#7c8a9e` / muted), chart paint binder leftovers from Phase 2 sign-off | Grok medium sign-off PASS (or documented waivers) |
| **U2** | B | **Predictive framing pass** — copy/UX per `docs/premium-dashboard-redesign.md` (“predicted to move +X% within N hours”); surface §16 hybrid score or honest “not enough data yet” where a score already appears | No new cockpit section IDs; no card sprawl in hero |
| **U3** | B | **Progressive enhancement (optional)** — htmx or deepen SSE/datastar hydration only where it removes full-page reloads without an SPA rewrite | Measurable: one hot path no longer full reload; a11y preserved |
| **U4** | B + Human | **Launch surface** — once P4 DNS exists: cache headers/CDN docs already in `DEPLOY.md`; brand/host polish on custom domain | Works on `dashboard.cryptoreporthub.com` when certs live |

**Out of U:** New 12th+ cockpit panels, theme rewrites, purple/glow aesthetic churn, marketing landing rebuild.

---

## §17.F — Big features

**Goal:** Product capabilities the FastAPI migration was meant to unlock — after trust + signals are sane.

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **F1** | A + B | **Streaming SimiVision chat** — harden `POST /api/simivision/chat` toward streaming responses (ASGI foundation); XSS-safe (`textContent`); rate limits already B6 | Stream or chunked response works in UI; contract test updated; no Flask resurrection |
| **F2** | A | **Live message-intel feed** — always-on Telegram listener ops (creds), richer cockpit `message_intel` than empty/warming | Prod `GET /api/message-intel` non-empty when creds present; honest-empty when not |
| **F3** | A + B | **Conviction alert delivery** — O1 backend exists; add real notify path (Telegram and/or email) behind existing flags | End-to-end notify in staging/prod with flag on; idempotent; no spam |
| **F4** | Human | **P4 custom domain** — `flyctl certs` + registrar CNAME (`DEPLOY.md`) | HTTPS on custom host |
| **F5** | B | **Report / backtest depth** — O2/O3 shipped; optional export formats or subnet deep-dive only if users ask | No speculative PDF engine |

**Out of F:** Second server entrypoint, external DB/broker, mobile native apps.

---

## Phase-level acceptance

| # | Check |
|---|--------|
| 1 | §16 complete (or explicit waive) before any §17 merge that displays new scores |
| 2 | Each slice has a one-line AC and stays inside ownership dirs |
| 3 | Honest-empty preserved; no fake live data |
| 4 | Board Gate Status lists §17 tracks; STATUS one-line updated per merge |

## Non-negotiables (same as master plan)

1. Honest-empty > decorative summaries > 500  
2. Never lower confidence thresholds to fake accuracy  
3. Single foundation: `server:app`  
4. No `data/*.json` commit churn  
5. Do not revert N/O/P merges or Step 0 spec  

## After §17

Idle / monitor. Further roadmap only if Ditto opens a new section — do not silently expand this file mid-build.
