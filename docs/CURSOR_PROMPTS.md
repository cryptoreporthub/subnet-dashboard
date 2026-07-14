CURSOR PROMPTS — Phase A (Ditto/Cursor split)
==========================================

These prompts hand off the Cursor-owned Phase A items from Ditto's EXTREME_AUDIT.md.
They reference the same source-of-truth docs Ditto wrote, so Cursor stays on the same page.

SOURCE-OF-TRUTH DOCS (read before starting)
-------------------------------------------
- docs/EXTREME_AUDIT.md        -> findings #11 (CORS) and #8 (cockpit resilience)
- docs/IMPLEMENTATION_PLAN.md  -> agreed split; A3 and A4 are Cursor-owned
- docs/GITHUB_TOOLING.md       -> security posture context
- docs/cursor-implementation-guide.md -> your own workflow (board, commit-per-task, pytest)
- docs/cursor-agents-communication/board.md -> live status

SHARED REFERENCE BLOCK (prepend to both prompts)
------------------------------------------------
You are working on cryptoreporthub/subnet-dashboard (FastAPI + Jinja2 SSR + Chart.js, Fly.io).
Read these first so we stay aligned with Ditto's audit:
- docs/EXTREME_AUDIT.md        -> authoritative findings (you're fixing #11 and #8)
- docs/IMPLEMENTATION_PLAN.md  -> agreed Ditto/Cursor split (these are Cursor-owned, Phase A)
- docs/GITHUB_TOOLING.md       -> security posture context
- docs/cursor-implementation-guide.md -> your own workflow (board, commit-per-task, pytest)

CONFLICT NOTE: cursor-implementation-guide.md lists "Fix X-Frame-Options invalid value" under
"Ditto Code Scope". That line is OUTDATED for this engagement — Ditto's GitHub tools cannot
rewrite server.py (>12k chars), so per IMPLEMENTATION_PLAN.md A3 it is YOURS. The plan
supersedes that one line.

WORKFLOW: update docs/cursor-agents-communication/board.md before starting; commit per task;
run pytest + python -m pytest tests/test_smoke.py before marking done; request human review.

==========================================================
PROMPT A3 — CORS / X-Frame-Options hardening (server.py)
==========================================================

TASK (audit #11). File: server.py :: add_cors_headers (the @app.middleware("http") function).
Current code on main, verbatim:

    @app.middleware("http")
    async def add_cors_headers(request: Request, call_next):
        """Allow dashboard embedding and cross-origin API access (parity with prior Flask behavior)."""
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["X-Frame-Options"] = "ALLOWALL"
        if request.url.path in _CACHE_PATHS:
            response.headers["Cache-Control"] = "public, max-age=30"
        return response

DO:
1. Replace X-Frame-Options: ALLOWALL with SAMEORIGIN. (ALLOWALL is not a valid XFO value —
   browsers ignore it, leaving the dashboard embeddable from any origin = clickjacking exposure.
   SAMEORIGIN is the safe value.)
2. Scope CORS off the wildcard. Add env var ALLOWED_ORIGINS (comma-separated, default
   "https://subnet-dashboard.fly.dev"). Reflect request Origin ONLY if in the allowlist;
   otherwise omit Access-Control-Allow-Origin. Add "Vary: Origin" when reflecting an allowed origin.
   - If you determine the public API genuinely needs open CORS, KEEP "*" but (a) document the
     decision inline + in docs/, and (b) flag it to the human for sign-off. Do NOT silently leave it open.
3. Leave the existing Cache-Control logic for _CACHE_PATHS unchanged.
4. Add a one-line comment citing audit #11.

DO NOT touch anything else in server.py.
Commit: fix(security): harden CORS + X-Frame-Options (audit #11).

==========================================================
PROMPT A4 — cockpit panel resilience (internal/cockpit/sections.py)
==========================================================

TASK (audit #8). File: internal/cockpit/sections.py. Target: ALL 12 _build_* functions
keyed by COCKPIT_SECTION_IDS (council_picks, judges, learning_loop, predictions,
scenario_memory, pump_ladder, pump_tracker, trace, message_intel, mindmap_trail, rotation, soul_map).

PROBLEM: each _build_* calls its submodule directly (e.g. _build_learning_loop calls
summarize_learning() and resolver.get_resolved_predictions()) with NO guard. If any submodule
raises (import/attribute/key error), the entire /api/cockpit/sections endpoint 500s and ALL 12
panels go blank — the exact "warming up forever" symptom.

FIX: wrap the BODY of EVERY _build_* in try/except Exception as _exc: that, on error, returns
_empty_copy(section_id, f"{SECTION_TITLES[section_id]} panel encountered an error: {_exc}",
status="unavailable") and calls logger.exception(...). This degrades a single broken panel to
"unavailable" instead of blanking the whole dashboard.

CONSTRAINTS:
- Do NOT change function signatures or happy-path behavior.
- Do NOT alter the _empty_copy / _live_section helpers.
- PRESERVE each function's existing empty-data branches (some already return _empty_copy for
  missing data — keep those; the new guard is only for UNEXPECTED exceptions).
- Run pytest + python -m pytest tests/test_smoke.py.

Commit: fix(cockpit): isolate panel errors so one failure can't blank all 12 (audit #8).
