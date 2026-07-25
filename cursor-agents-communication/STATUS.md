# STATUS

**Updated:** 2026-07-25T00:15:00Z  
**main:** see `board.md` / latest merge  
**active plan:** `prod-stability-plan.md` (Phases 0–4) · pump gameplan Waves 0–3 **shipped** · G0 human QA **open**

## Next (sequential — one PR at a time)

1. **Phase 0** `cursor/reconnect-smoke-d2cd` — verify no real 422s; B0-0 Quiet gate
2. **Phase 1** `cursor/pump-alerts-fast-d2cd` — fast desk API; stop caching timeouts (**critical**)
3. **Phase 2** `cursor/pump-desk-compact-d2cd` — compact Warming/Active UI
4. **Phase 3** `cursor/hydrate-stability-d2cd` — sequential hydrate + prod gates
5. **Phase 4** `cursor/chat-context-fast-d2cd` — after site stable (optional)

**Also open:** G0 human 390px · P5 founder chip · E1 test debt (`post-s28-backlog.md`)

## Done (recent)

- #410 — full plan execution: G0 script, Wave 2–3 (S1–S8), P4 notify
- #430–#436 — day-whale + slip chips, TaoStats ingest, CI bg-scan fix
- #437 — Fly Phase B: `BACKGROUND_ON_WEB=essential` + worker process group
- #442–#446 — subnet integration badges, dossier crumbs, brain letter strip
- #419 — Slice R+M (rebalance + pump score overlay)
- §34 + subnet-names (#325) · §33 prod readiness · §31 website opt

## Gameplan slice summary

| ID | Status |
|----|--------|
| G0 | ⚠️ script only |
| P1–P4, S1–S2, S4–S8 | ✅ |
| P5, S3 | ⚠️ partial |
| Wave 4 | — skipped |

## Skipped

- H1 custom domain until human · Wave 4 depth · D1–D7 deferred features
