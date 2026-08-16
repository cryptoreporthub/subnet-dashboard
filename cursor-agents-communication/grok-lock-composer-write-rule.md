# Grok lock → Composer write — RETIRED as a hard token-save (2026-08-16)

Human request: agents write at natural length. Do **not** require a ~1-screen Grok LOCK before Composer may plan or build.

Optional structured LOCK (when a short decision record helps):

```
VERDICT: PASS | CONDITIONAL | FAIL
DECISIONS: (3–7 bullets)
FILES: ...
AC: ...
RISKS / NON-GOALS: ...
ESCALATE_HIGH?: no | yes (why)
```

Still useful, unrelated to brevity:

- Conflict surface: `server.py` `include_router` + `tests/test_endpoint_contract.py` — rebase before merge if both tracks changed them.
- `.cursorignore` — do not force-read `data/*.json`.

See `token-budget-rules.md` (retired + billing watch).

Subagent pool (2026-08-16): Composer slow (`composer-2.5`), Grok 4.6 medium, GPT-4.6 Luna high. Never Sonnet 4.5 or 4.6 — `.cursor/rules/subagent-models.mdc`.
