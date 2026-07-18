CURSOR PROMPTS — K3 Phase 1 (K3-2 merge + K3-2b data wire)
====================================================================

These prompts hand off Phase 1 of the K3 phased rollout to Cursor. They reference the
source-of-truth docs on main so Cursor stays on the same page.

SOURCE-OF-TRUTH DOCS (read before starting)
-------------------------------------------
- docs/K3-Master-Architecture-V2.md   -> authoritative plan. Section 4A = data contract,
                                          Section 5 = slice queue, Section 9 = handoff gates
- docs/k3-2-deliberation-spec.md      -> K3-2 frontend spec (deliberation layer already coded)
- docs/cursor-implementation-guide.md -> your workflow (board, commit-per-task, pytest)

CONFLICT NOTE: K3-Master-Architecture-V1.md and older plan docs (master-plan-merged.md,
premium-dashboard-redesign.md, etc.) are SUPERSEDED for K3 scope. V2 is the plan of record.
If any older doc contradicts V2 (slice order, K3-2 status, /api/lifecycle, file paths,
dossier.css/ring.css), V2 wins.

SHARED REFERENCE BLOCK (prepend to both prompts)
------------------------------------------------
You are working on cryptoreporthub/subnet-dashboard (FastAPI + Jinja2 SSR, Fly.io deploy
at subnet-dashboard.fly.dev). Read docs/K3-Master-Architecture-V2.md first — Sections 4A,
5, and 9 are normative for this phase.

LOCKED SLICE ORDER (do not reorder, do not skip):
    K3-2 merge  ->  K3-2b data wire  ->  USER PHONE SIGN-OFF  ->  K3-3 ...
You own K3-2 merge and K3-2b. You do NOT own K3-3 yet. STOP after P2 (see STOP GATE).

WORKFLOW: update docs/cursor-agents-communication/board.md before starting; commit per
task; run pytest + python -m pytest tests/test_smoke.py before marking done; CI gates 1-8
must stay green (GATE 5 skipped is normal for docs-only).

====================================================================
PROMPT K3-P1 — Merge PR #346 (K3-2 deliberation layer)
====================================================================

TASK: Land the already-coded K3-2 deliberation layer on main.

CONTEXT: PR #346 "K3-2: Council considered deliberation flow"
- Branch: cursor/k3-2-deliberation-e7f9, base: main, currently DRAFT
- mergeable_state: clean. Changed files: 1 — templates/partials/premium/council_stage.html (+60)
- CI gates 1-8 green on the branch (GATE 5 skipped, normal)
- NOTE: PR #345 was a duplicate draft and is now CLOSED. Ignore it.

DO:
1. Run the V2 Section 9 pre-build repo verification checklist against main.
2. Mark PR #346 ready for review and squash-merge it to main:
       gh pr ready 346
       gh pr merge 346 --squash
3. Post-merge verification on main:
   - templates/partials/premium/council_stage.html contains the deliberation layer markup
   - Homepage renders on subnet-dashboard.fly.dev after fly.yml redeploy completes
   - Deliberation layer renders its honest-empty state ("Council deliberation in progress")
     — dpick.shortlist data does NOT exist yet; empty is the CORRECT behavior here
4. Wait for the Fly deploy to reflect the merge SHA before starting P2.

DO NOT touch any other file. DO NOT start K3-2b until the deploy is live and verified.
Commit: (squash merge commit only)

====================================================================
PROMPT K3-P2 — K3-2b: wire dpick.shortlist data source
====================================================================

TASK: Populate dpick.shortlist, the data consumed by the deliberation layer merged in P1.
Spec: V2 Section 4A. This blocks phone sign-off.

DEFAULT APPROACH (per V2 §4A): extend the EXISTING GET /api/mindmap/summary handler in
internal/learning/routes.py — add a "dpick": {"shortlist": {...}} block to the response
"data". Do NOT create /api/deliberation/shortlist unless extension proves messy; if you
deviate, flag it in the board and in your report.

PAYLOAD SHAPE (V2 §4A, normative):
    {
      "picked": {"netuid": 82, "name": "MinoS", "conviction": 78},
      "alternatives": [
        {"netuid": 14, "name": "SN14", "conviction": 62,
         "why_not": "Lower volume liquidity", "rank": 2}
      ],
      "total_considered": 8,
      "council_unanimous": false,
      "dissenters": ["Echo"],
      "last_updated": "2026-07-18T15:00:00Z"
    }
- alternatives: 3-8 entries, ranked by council conviction, excluding the pick
- why_not: judge note / dissent reason when available, else null
- dissenters: judges who flagged the pick, [] if unanimous

DATA SOURCE: derive from the existing council ranking already used by this endpoint —
internal.council.daily_pick_engine.get_or_create_today_pick plus the _safe_simivision_payload
snapshot (both already imported/used in api_mindmap_summary). picked = today's pick;
alternatives = next-highest-conviction subnets not picked. No new data pipelines.

CONSTRAINTS:
- ADDITIVE ONLY: do not rename, retype, or reorder any existing /api/mindmap/summary
  field — GATE 2 (contract parity) must stay green.
- HONEST-EMPTY: if fewer than 2 alternatives are derivable or data is thin, return
  "shortlist": [] — the frontend already renders the honest-empty card for that case.
- FAULT ISOLATION: wrap the shortlist build in try/except; on any failure log and return
  "dpick": {"shortlist": []} — a shortlist error must NEVER 500 the summary endpoint.
- No new dependencies. No changes to council_stage.html (it already reads dpick.shortlist).
- Run pytest + python -m pytest tests/test_smoke.py; extend the contract test to assert
  the dpick.shortlist key exists with correct types (list, int netuids, float/int conviction).

Commit: feat(learning): wire dpick.shortlist into /api/mindmap/summary (K3-2b)
Board: update docs/cursor-agents-communication/board.md.

====================================================================
STOP GATE — USER PHONE SIGN-OFF
====================================================================

After P2, STOP. Report back with:
1. PR #346 squash-merge SHA
2. A sample dpick.shortlist JSON payload from the live deploy
3. Confirmation the honest-empty card renders when shortlist is []
4. CI gates 1-8 status on main after both commits

Do NOT start K3-3 (story-path promotion). The user performs phone sign-off on
subnet-dashboard.fly.dev (V2 Section 5 Phase 2 checklist) before K3-3 is greenlit.

NOTE for later (NOT Phase 1 scope): live /api/mindmap/story-path returned 422 to a bare
GET during V2 verification; main's handler is a no-param route. Verify deployed behavior
vs main before K3-3 begins.