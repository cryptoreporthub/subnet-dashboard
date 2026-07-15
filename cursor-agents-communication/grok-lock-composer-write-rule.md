# Shared rule — Grok lock → Composer write (token-save)

**Send this to Agent A and Agent B** (same text both). Binding also in `model-guide.md` + `s16-s17-automated-build-plan.md`.

```
HARD RULE (token-save) — both Agent A and Agent B must obey through end of §17:

1) Grok = thinking only. Use slow Grok + medium thinking. Escalate to high ONLY if medium FAIL/CONDITIONAL or output unsatisfactory. Do not default to fast-xhigh or xhigh.

2) When a slice needs design (plan marks DESIGN, or path is ambiguous): spawn Grok read-only and demand a SHORT structured LOCK — not a long markdown plan. Cap ~1 screen:

VERDICT: PASS | CONDITIONAL | FAIL
DECISIONS: (3–7 bullets)
FILES: ...
AC: ...
RISKS / NON-GOALS: ...
ESCALATE_HIGH?: no | yes (why)

3) Composer writes the plan file / PR body / board lines FROM that lock, then builds. Composer must not invent design details missing from the lock. Grok must not author long prose plans.

4) If s16-s17-automated-build-plan.md (or Step 0 / phase spec) already locks the slice, skip a new Grok pass — Composer builds from the approved plan. No Plan mode every slice.

5) Auto-continue your queue when CI is green and gates are clear. QB is this human chat — Ditto is gate/spot-check only.

6) Conflict surface: server.py include_router + tests/test_endpoint_contract.py — rebase before merge.

Current next (as of GATE_S_CORE clear after #252): A → F1 watchlist API; B → U1 single-job home. Re-read board.md + STATUS.md on latest main before building.
```
