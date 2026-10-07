# PROBE-LIVE-CONFIG — DRAFT ONLY (DO NOT RUN)

**Status:** DRAFT — awaiting separate Joshua Go to execute  
**Approver:** Joshua  
**Drafted:** 2026-09-20T13:17Z  
**Pin context:** campaign pin `c9449d6490231373748f19f299ed19d423a1c971` (code-only); this probe would observe live prod/runtime only

## Purpose
Read-only observation of live process/env and/or filesystem facts that remain NOT_OBSERVABLE from repo blobs (e.g. live WRITE_TIMEOUT / WORKER_HEAVY / whether orphan late-write advances score_snapshots.json mtime in prod).

## Blast radius
- **In scope:** read-only HTTP (`/version`, maybe status endpoints already public), and/or read-only listing of deployed artifact metadata if an approved read-only workflow exists.
- **Out of scope / cannot affect:** deploys, Fly machine restarts, secret mutation, writes to `data/`, scheduler triggers, traffic generation beyond a single GET, any code change on PR #1294 or main.

## What it cannot affect
- Application code, config files in git, secrets, machine lifecycle, background job schedules, user data mutation.

## Proposed steps (NOT AUTHORIZED until Go)
1. GET prod `/version` — timestamped receipt (pin check only).
2. Optional: GET existing read-only status endpoints already in contract tests — no new routes.
3. Stop. Report raw JSON + timestamps. No follow-on actions.

## Explicit non-actions
- Do not `flyctl`, do not SSH, do not `touch`/`write` snapshot files, do not run pytest against prod, do not open remediation PRs.

## Approval line
`STATUS: DRAFT — do not run without separate Joshua Go naming this probe.`
