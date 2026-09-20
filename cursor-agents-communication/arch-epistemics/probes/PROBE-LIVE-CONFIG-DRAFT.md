# DRAFT — Read-only live-config probe (DO NOT RUN)

**status:** draft_only  
**created:** 2026-09-20T00:44Z  
**created_by:** mission-control  
**joshua_go_to_execute:** REQUIRED before any run  
**related:** F-1b (live WORKER_HEAVY NOT_OBSERVABLE), C-016, F-1

## Purpose
Observe whether named process env keys are visible via an already-public or explicitly approved read-only surface, enough to close F-1b / raise config claims toward Tier A. Prefer surfaces that cannot return Fly secrets.

## Named approver
- **Approver:** Joshua  
- **Second approver (optional):** none unless Joshua names one  
- **MC may not self-approve.**

## Proposed methods (pick one at Go time)
1. **Public `/version` only** (already captured as E-PROD-VERSION) — confirms deploy pin; **cannot** read WORKER_HEAVY.  
2. **Existing public health/config redacted endpoint** (if one exists at pin) — inventory first code-only; run only if endpoint is already public and redacts secrets.  
3. **GitHub Actions read-only workflow** (previously designed, never run) — inspect machine config inventory without MC shell `flyctl` — requires separate workflow Go + blast note.  
4. **Forbidden without new Go:** `flyctl ssh`, `fly secrets`, scraping private admin, injecting debug routes, printing `os.environ` in prod.

## Blast radius
- **In scope if approved:** one GET to a named public URL, or one read-only GH Actions workflow dispatch already reviewed.  
- **Max requests:** 1–3 GETs.  
- **No writes, no deploys, no secret listing, no SSH, no config mutate.**

## What it cannot affect
- Fly machines / scale / image  
- Fly secrets store  
- Process env  
- Deploys / releases  
- Ditto / Ledger claim tiers (MC records evidence; Joshua still promotes)  
- Customer data paths beyond the single public GET body  

## Success / fail
- **Success:** documented response body + timestamp + whether WORKER_HEAVY (or named keys) appear; if absent → remains NOT_OBSERVABLE.  
- **Fail/abort:** any auth wall, secret material in body, or non-GET method required.

## Current standing evidence (already attached; not a probe run)
- `evidence/E-PROD-VERSION-2026-09-20.json` — GET https://subnet-dashboard.fly.dev/version @ 2026-09-20T00:44:36Z  
- Body: version c9449d6 / sentry_release = campaign pin / python 3.12.14  
- **Does not close F-1b.**

## Explicit non-execution
This file is a draft. **No probe was run** under this Go except the already-public `/version` capture requested as pin evidence.
