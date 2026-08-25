# P5 — Browser SDK Implementation Plan (documentation only)

**Status:** Plan only — **no implementation until explicit separate approval.**  
**Directive:** Sentry Telemetry Review v1.1, Patch P5 (read-only discovery in Phase 0; implementation gated).  
**Related:** [`docs/sentry-telemetry-findings.md`](sentry-telemetry-findings.md) (server-side Waves 1–2, Stages B–D).  
**Out of scope:** Saga/D5/hydration workstreams, `server.py` hydration logic, Session Replay (separate track), server tracing, alert activation (Stage D).

---

## Summary

The Subnet Dashboard ships **vanilla static JavaScript** (no bundler, no `package.json`). Server-side Sentry is live on production (`internal/sentry_setup.py`, Path B scrub merged #1038, Fly `v2008`). The browser has **no** client error monitoring today. This document is the implementation blueprint for a future PR — it does not change runtime behavior.

---

## Prerequisites and gates (must pass before any code PR)

| Gate | Status (2026-08-25) | Required for P5 |
|------|---------------------|-----------------|
| Path B server scrub/filter (#1038) | **MERGED** — live prod `v2008` | Yes |
| Stage C release tags (#1042) | **PR open** — Dockerfile `SENTRY_RELEASE` + fly.yml verify | **Yes** — browser `release` must match server deploy SHA for regression detection |
| Stage C deployed to prod | Pending merge + authorized deploy | Yes — verify `release` tag on prod events before browser rollout |
| P3 quota/tier check | **Pending** — manual Sentry Settings → Subscription | Yes — browser errors add ingest; confirm headroom |
| Explicit owner approval for P5 implementation | **Not granted** | Yes — this doc is not approval |
| Session Replay privacy/quota gate | Not started | No for initial Browser SDK (Replay is a separate track) |
| Saga `/subnetsummer` server capture | Pending | No blocker for browser SDK (orthogonal) |

**Recommended merge order**

1. Merge **#1042** (Stage C) and complete authorized deploy + `SENTRY_RELEASE` verify on machine.
2. Wait ≥24h post-scrub baseline; complete manual quota check.
3. Owner approves P5 implementation explicitly (reference this doc).
4. Open implementation PR on `cursor/sentry-browser-sdk-*` — **no overlap with #1042**.

**Do not** bundle Browser SDK changes into #1042 or any Saga/hydration PR.

---

## Current frontend state (Phase 0 discovery — confirmed from code)

| Item | Finding |
|------|---------|
| `@sentry/browser` | **Not installed** — no npm/bundler; assets are plain `<script src="/static/...">` |
| Source maps | **None** — no `.map` files shipped; stack traces will be minified-line only unless maps uploaded later |
| Error surfaces | No `window.onerror`, `unhandledrejection`, or `captureException` in `static/` |
| CSP | `internal/security_headers.py` — default report-only policy |
| Sentry project | Single project **python-fastapi** (org simivision); server DSN is Fly secret |
| Release attribution | Server reads `SENTRY_RELEASE` env (Stage C adds build-time bake) |

### Template / script load spine

```
base.html (all pages extending it)
  └── body end: app.js, chat_stream.js, judge_panel.js, command_palette.js, driver.js (cdn), onboarding, council_polish

index.html (homepage cockpit)
  └── partials/premium/scripts.html
        └── inline apiFetchJson bootstrap
        └── subnet-group-data JSON blob
        └── 20+ deferred hydrators ending in cockpit_hydrate.js, message_intel_feed.js, home_live_refresh.js, …

listener.html, simivision.html, judge_council.html, share/* — standalone templates, NOT all extending base.html
```

**Homepage-critical path:** `cockpit_hydrate.js` (~5.6k lines) drives JSON API hydration for the fast shell. **Do not modify hydration logic for Sentry.** Loader must be additive and early enough to catch errors in deferred scripts without changing hydrate behavior.

---

## Loader placement options

### Option A — `templates/base.html` `<head>` (recommended)

Inject a small inline bootstrap or first `<script src="/static/js/sentry_init.js">` in `<head>` before other scripts.

| Pros | Cons |
|------|------|
| Covers every page that extends `base.html` (homepage, pump previews, pump.html) | Does **not** cover `listener.html`, `simivision.html`, `judge_council.html`, `share/*` unless those templates also include the partial |
| Catches parse/load errors in downstream deferred scripts as early as possible | Inline init needs CSP `unsafe-inline` (already allowed) or external file on `'self'` |
| Single inclusion point | Must not block first paint — use `async` loader pattern or tiny inline stub |

### Option B — `templates/partials/premium/scripts.html` only

| Pros | Cons |
|------|------|
| Minimal blast radius (homepage cockpit only) | Misses errors in `base.html` scripts (`app.js`, `chat_stream.js`) and non-homepage routes |
| Far from hydration logic (included before hydrator list) | Poor fit for site-wide client monitoring goal |

### Option C — New partial `partials/sentry_browser.html` included from `base.html` + standalone pages

| Pros | Cons |
|------|------|
| Full coverage when wired into each top-level template | More template touches; share pages may need a lighter config |
| Keeps `base.html` clean | Slightly more maintenance |

### Option D — Server-injected config endpoint `/api/telemetry-config` (no DSN in HTML)

| Pros | Cons |
|------|------|
| DSN not in page source; can gate on env flag | Extra round-trip delays init; fetch can fail silently; still need loader script |
| Easier to disable without redeploy | Adds API surface + contract test entry |

**Recommendation:** **Option A + C** — `partials/sentry_browser.html` included from `base.html` `<head>`, and manually added to `listener.html` / `simivision.html` / `judge_council.html` / `share/base_share.html` in the implementation PR. Homepage hydrators stay untouched.

---

## SDK delivery strategy (no bundler today)

Because there is no `package.json`, prefer **vendoring** over CDN:

1. Copy `@sentry/browser` IIFE bundle to `static/vendor/sentry/browser.min.js` (pinned version, documented in commit).
2. Add `static/js/sentry_init.js` — thin wrapper: read config, `Sentry.init({...})`, register global handlers.
3. **Do not** add `https://browser.sentry-cdn.com` to CSP unless product explicitly wants CDN — vendoring keeps `script-src 'self'` satisfied.

Alternative (not preferred): add `https://browser.sentry-cdn.com` to `script-src` — widens CSP third-party surface.

---

## Public DSN strategy

| Approach | Notes |
|----------|-------|
| **Same Sentry project, separate client key** (recommended) | Create a second DSN in project **python-fastapi** (Client Keys). Server keeps Fly secret `SENTRY_DSN`; browser uses `SENTRY_BROWSER_DSN` Fly secret rendered server-side only when `SENTRY_BROWSER_ENABLED=1`. Allows independent key rotation and rate-limit policies. |
| Same DSN for server + browser | Simpler ops; harder to rotate browser key without server churn; events mixed in one key stream. |
| Separate Sentry project (e.g. `javascript-browser`) | Cleanest separation; more quota overhead; cross-release correlation needs shared `release` tag discipline. |

**Exposure model**

- DSN is **public by design** in browser SDKs — security relies on ingest key restrictions + scrubbing, not secrecy.
- Inject via Jinja global from env (e.g. `sentry_browser_dsn`) only when enabled; never commit DSN to repo.
- Pass `environment: production` (match server `SENTRY_ENVIRONMENT`).
- Pass `release: {{ sentry_release }}` from same `SENTRY_RELEASE` env Stage C bakes — **must match server** for release health.

**New env vars (implementation PR only)**

| Variable | Where | Purpose |
|----------|-------|---------|
| `SENTRY_BROWSER_ENABLED` | Fly `[env]` or secret | Feature flag — default off |
| `SENTRY_BROWSER_DSN` | Fly secret | Public browser ingest key |
| `SENTRY_RELEASE` | Image env (Stage C) | Shared release tag |

---

## CSP changes (`internal/security_headers.py`)

Current default (`_DEFAULT_CSP_REPORT_ONLY`):

```
script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net
connect-src 'self' https: wss:
```

| Need | Change |
|------|--------|
| Ingest POST | `connect-src` already allows `https:` — **no change required** for `*.ingest.sentry.io` |
| Vendored SDK | `script-src 'self'` — **no change** if bundle is self-hosted |
| CDN SDK (alt) | Add `https://browser.sentry-cdn.com` to `script-src` |
| Session Replay (future) | May need `worker-src blob:` — **not in initial P5** |
| Enforced CSP | Today report-only unless `CONTENT_SECURITY_POLICY_ENFORCE=1` — test both modes before enforce |

**Implementation checklist**

1. Ship with report-only CSP first; confirm zero new CSP violations in browser console.
2. If using env override `CONTENT_SECURITY_POLICY`, document the full merged policy in DEPLOY.md (implementation PR).
3. Do not tighten `connect-src` away from `https:` — would break Sentry and existing font/CDN fetches.

---

## Source maps strategy

| Phase | Approach |
|-------|----------|
| **Initial P5** | **No source maps** — accept obfuscated line numbers in `static/js/*.js` (files are unminified but large). Sufficient for first client error signal. |
| **Follow-up (optional)** | Upload maps at deploy via `sentry-cli releases files <release> upload-sourcemaps static/js` in fly.yml post-build step; do **not** serve `.map` publicly. Requires `SENTRY_AUTH_TOKEN` GitHub secret + org auth. |
| **Inline source maps** | **Reject** — exposes full source to users and bloats payloads. |

Release matching: browser events must set `release` to the same git SHA Stage C writes to `SENTRY_RELEASE` so uploaded maps (if added later) resolve correctly.

---

## Client-side scrubbing (`beforeSend` equivalent)

Mirror server patterns in `internal/sentry_setup.py` — do not duplicate business logic in hydrators.

| Pattern | Server reference | Browser action |
|---------|------------------|----------------|
| Telegram `@handles` | `_HANDLE_RE` | Strip/redact in `event.message`, breadcrumb messages, `extra` strings |
| Bearer / Authorization | `_BEARER_RE`, `_AUTH_HEADER_RE` | Drop or redact from breadcrumbs and request headers |
| Sensitive headers | `_SENSITIVE_HEADER_NAMES` | Never attach `cookie`, `authorization`, `x-api-key` in `Sentry.setContext('request', …)` |
| Message-intel bodies | pump / feed DOM text | Do not capture full feed HTML or message bodies in breadcrumbs — use route + element id only |
| `subnet-group-data` JSON blob | `scripts.html` inline JSON | Do not serialize `#subnet-group-data` into contexts (may contain picks/predictions) |
| PII default | `send_default_pii=False` (server) | Set `sendDefaultPii: false` on browser |

**Drop rules (client)**

- Ignore errors from browser extensions (`chrome-extension://`, `moz-extension://`).
- Optionally ignore benign `AbortError` from `api_fetch.js` timeouts if volume is noisy (match server TaoStats drop discipline — measure first).
- Never attach chat prompt/completion content from `chat_stream.js`.

Implement scrubbing only in `static/js/sentry_init.js` — **one file**, not per-hydrator patches.

---

## Duplicate server + browser event deduplication

| Scenario | Risk | Mitigation |
|----------|------|------------|
| API 500 captured server-side + fetch failure in browser | Duplicate issues for same root cause | Tag browser events `tags: { runtime: 'browser' }`; server already tags via SDK platform. Filter alerts by platform. |
| Unhandled rejection after failed `/api/*` | Two events (HTTP server + client promise) | Do not wrap `api_fetch.js` with automatic `captureException` on every HTTP error — rely on global unhandledrejection + manual `captureException` only for unexpected throws. |
| Same error bubbled to both | Rare for this stack | Use `Sentry.withScope` sparingly; set `fingerprint` only when a known duplicate pattern appears in QA |

**Policy:** Browser SDK captures **uncaught JS errors** and **unhandled promise rejections** — not routine HTTP 4xx/5xx from `fetch` unless explicitly escalated after volume review.

---

## Session Replay — separate gated track

**Not in initial P5.** Requires:

- Owner approval + privacy review (Telegram handles, wallet addresses, council picks on screen).
- Quota/tier check (Replay is billed separately on many plans).
- CSP `worker-src` / additional SDK bundle.
- `replaysSessionSampleRate` / `replaysOnErrorSampleRate` env-gated defaults of **0**.

Document as **P5b** follow-up after browser error baseline is stable ≥7d.

---

## Conflict surface — files that would be touched (implementation PR)

| File | Change type | Risk |
|------|-------------|------|
| `static/vendor/sentry/browser.min.js` | **New** — vendored SDK | Low — vendor pin |
| `static/js/sentry_init.js` | **New** — init + scrub | Low — isolated |
| `templates/partials/sentry_browser.html` | **New** — loader include | Low |
| `templates/base.html` | Include partial in `<head>` | Medium — all base pages |
| `templates/listener.html`, `simivision.html`, `judge_council.html`, `share/base_share.html` | Include partial | Medium — coverage |
| `server.py` or template globals | Expose `sentry_browser_dsn`, `sentry_release`, enabled flag | Low — env-gated |
| `internal/security_headers.py` | CSP only if CDN chosen | Low if self-hosted |
| `internal/static_version.py` | Add `sentry_init.js` to `_ASSETS` if cache-busted | Low |
| `tests/test_endpoint_contract.py` | Only if `/api/telemetry-config` added | Low |
| `fly.toml` / secrets | `SENTRY_BROWSER_*` | Approval-gated |
| `.github/workflows/fly.yml` | Source map upload (optional follow-up) | Keep out of initial PR |

### Explicit do-not-touch (implementation)

| File | Reason |
|------|--------|
| `static/js/cockpit_hydrate.js` | Hydration / Saga surface — no Sentry hooks in hydrate path |
| `internal/sentry_setup.py` | Server-only unless doc-accuracy fix — browser is separate init |
| `server.py` hydration routes | User constraint |
| Saga/D5 modules | Unrelated workstream |

---

## PR strategy

| Item | Value |
|------|-------|
| Branch | `cursor/sentry-browser-sdk-<suffix>` (e.g. `cursor/sentry-browser-sdk-72e0`) |
| Base | `main` after #1042 merged |
| Overlap | **None** with #1042 (`cursor/sentry-release-docker-72e0`) |
| Scope | Browser loader + init + CSP verify + tests/docs — no Replay, no tracing |
| Deploy | Requires explicit `workflow_dispatch` / owner approval per AGENTS.md |
| Feature flag | `SENTRY_BROWSER_ENABLED=0` default until post-deploy verify |

This plan doc PR: `cursor/sentry-browser-plan-72e0` (documentation only).

---

## Testing plan (implementation phase — manual browser, no Replay)

1. **Local**
   - Set `SENTRY_BROWSER_DSN` + `SENTRY_BROWSER_ENABLED=1` in shell; run `python server.py`.
   - Open `/` — confirm `sentry_init.js` loads (Network tab), no CSP violations.
   - DevTools console: `throw new Error('sentry-browser-verify-local')` — confirm event in Sentry with `runtime: browser`, `environment: development`, `release` matching local `SENTRY_RELEASE` if set.
   - Load `/listener` (if enabled) — confirm loader present on standalone template.
   - Regression: homepage hydration still completes (`data-hydrate` clears, daily pick renders) — **no changes to cockpit_hydrate.js**.

2. **Staging / prod (after authorized deploy)**
   - Trigger one intentional verify error via console (not automated in CI).
   - Confirm single event; no duplicate server issue for same action.
   - Confirm `@handle` redaction: paste fake `@testuser` in thrown message — must not appear raw in Sentry.

3. **Automated (optional, implementation PR)**
   - Unit test for scrub helpers in `sentry_init.js` if extracted to testable functions, or thin Python test that template omits DSN when flag off.
   - `tests/test_endpoint_contract.py` stays green.

**No Playwright requirement for P5** — manual browser verify is sufficient per directive.

---

## Rollback plan

| Step | Action |
|------|--------|
| 1 | Set `SENTRY_BROWSER_ENABLED=0` on Fly (or unset `SENTRY_BROWSER_DSN`) — immediate stop of new browser events |
| 2 | Redeploy not required if env-only; if loader is unconditional, revert implementation PR |
| 3 | Remove/disable client key in Sentry UI if key was compromised |
| 4 | No Saga/runtime/hydration state to unwind |

Browser SDK rollback is **independent** of server Sentry (Path B) and Stage D alerts.

---

## Success criteria (implementation — future)

- [ ] Browser uncaught error appears in Sentry with `environment:production`, `release:<deploy-sha>`, platform JavaScript.
- [ ] No increase in CSP report-only violations attributable to Sentry.
- [ ] Homepage hydration behavior unchanged (manual smoke).
- [ ] Scrubbing verified for handles and auth-like strings.
- [ ] Quota impact documented after 24h observation.
- [ ] Session Replay remains disabled.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-08-25 | Initial P5 plan — documentation only (`cursor/sentry-browser-plan-72e0`) |
