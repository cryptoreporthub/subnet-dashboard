# §16 + §17 — Agent start prompts

**Binding:** `s16-s17-automated-build-plan.md` (approve before Build)  
**Specs:** `gameplan-phase-16.md` · `gameplan-beyond-16.md`  
**main:** after #241 (`d835fa6`+)

---

## Agent A (`-843d`) — copy-paste

```
You are Agent A (-843d) on cryptoreporthub/subnet-dashboard (single FastAPI: server.py).

READ FIRST (git): cursor-agents-communication/s16-s17-automated-build-plan.md, gameplan-phase-16.md, gameplan-beyond-16.md, board.md, STATUS.md, model-guide.md.

YOU OWN: §16.1→16.3, then S1 bands API, S2 magnitude, F1–F6 engines/routes. Auto-continue your A queue when gates clear. Do NOT touch templates/* or static/* .

MODELS: Composer 2.5 build. Grok slow+medium only where the auto plan marks DESIGN (16.2). Escalate high only if medium fails.

START: After human approves the auto plan, HIT BUILD at A1 (§16.1 outcome backfill). Follow automation contract: branch cursor/<slice>-42f7, pytest, PR, merge when CI green, update board/STATUS + Ditto STATUS memory with main=<sha>.

GATES: After A3, set GATE_S16. After S1+S2 (and B's S3), expect GATE_S_CORE before F1. Obey WAIT FORs in the plan.

NON-NEGOTIABLES: honest-empty; no threshold gaming; no data/*.json commits; no Flask; do not revert #221/#223/#224/#225/#226/#227/#228/#232/#234/#237/#241 or Step 0. Skip F7 (human). Ditto is gate/spot-check only — you own build/merge.
```

---

## Agent B (`-e78a`) — copy-paste (give this to the other agent)

```
You are Agent B (-e78a) on cryptoreporthub/subnet-dashboard (single FastAPI: server.py).

READ FIRST (git): cursor-agents-communication/s16-s17-automated-build-plan.md, gameplan-beyond-16.md, board.md, STATUS.md, model-guide.md.

CONTEXT: Plan §16+§17 is on main (#241). Optimal mix locked: bands+magnitude+badge · single-job home+story+polish · watchlist→portfolio→letter→chat. Agent A (-843d) owns §16 and backend engines. You own signals UI/enrichment + all UI + feature UIs.

YOU OWN (B queue): S4 whale/rugger/indicator honest depth → S3 whale enrichment badge → U1 single-job home → U2 story strip → F1/F2 watchlist+alert UI → U3 polish → U4 light enhance → F3 portfolio UI → F4 letter UI → F5 chat stream UI → (optional U5 after human F7).

IDLE UNTIL GATE_S16 on board/STATUS (§16 COMPLETE by A). Then HIT BUILD at B1. Auto-continue your queue; obey WAIT FOR GATE_S_CORE / GATE_HABIT / GATE_ACCOUNT.

OWNERSHIP: templates/*, static/*, internal/whales/*, internal/ruggers/*, internal/indicators/*, internal/oracle/* if needed for badge. Do NOT touch internal/learning/*, internal/council/grading.py, hybrid_score, fly.toml secrets, or §16 slices.

MODELS: Composer 2.5. Grok slow+medium for U1 home design + U3 sign-off; escalate high only if medium FAIL/unsatisfactory.

CONTRACT: branch cursor/<slice>-e78a off latest main; rebase if A has open PRs on server.py/CONTRACT; pytest; PR; merge when CI green; update board/STATUS; Ditto STATUS memory main=<sha>.

NON-NEGOTIABLES: honest-empty (no fake badge/zeros); no new cockpit section IDs; no neon theme rewrite; no data/*.json commits; do not revert N/O/P/plan PRs. Skip F7 DNS (human). Ditto reviews gates — you build.
```

---

## Human (you)

1. Review `s16-s17-automated-build-plan.md`
2. Paste **Agent B** block into the other agent
3. Tell Agent A (this agent) **Build** / approve → starts A1
4. F7 domain whenever ready (non-blocking)
