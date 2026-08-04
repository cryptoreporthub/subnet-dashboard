# Phase 2 — Visual polish execution plan

**Created:** 2026-08-04  
**main at plan:** `5dd47b5` (#802 Tranche 1, #803 message-intel reset script)  
**Live:** https://subnet-dashboard.fly.dev  
**Runtime:** FastAPI + Jinja (not Flask) — templates/CSS/JS only unless flagged

---

## 1. Goals (what Phase 2 is)

| Goal | Success looks like |
|------|-------------------|
| **Hip, current, sleek** | Dark glass cards, amber/cyan/lime accents, subtle motion (conic edge-glow, sparklines, halo pulse) |
| **Live, not placeholder** | Hero + desks show real endpoint data; no hardcoded demo numbers |
| **Honest empty** | Tranche 1 done — do not regress `desk-empty-state` / progress patterns |
| **Sequential delivery** | One subagent → one PR → merge → babysit → next |
| **No council-engine edits** | Front-end + hydrate wiring only |

**Phase 3 (explicitly NOT Phase 2):** full `ui-legacy.css` purge, fixing `test_council_stage_h1/h2_*`, accuracy soak experiments, council scoring changes.

---

## 2. Already on main (do not re-open)

| Item | PR / note |
|------|-----------|
| Empty states + thumb dock + hero `data-*` hooks | #802 |
| Tribunal hero live-wired + `patchTribunalJudges/Metrics` | #796 |
| Pewter smoke pick card | #798 |
| Message-intel **prod reset** (keep 3d, 879 msgs remain) | Ran 2026-08-04 via #803 script |
| `reset_message_intel.py` for future ops | #803 |

---

## 3. Model workflow (mandatory)

| Role | Model | When |
|------|-------|------|
| **Baseline + mechanical build** | Composer 2.5 (`composer-2.5-fast` for token-only edits) | Subagent 0, font swap, hydrate gaps, CSS from LOCK |
| **Two visual ideas per section** | **Grok slow + medium** | Before Subagents 2–5 only — returns short LOCK (not long prose) |
| **Diff review (optional)** | Sonnet low on diff | Only if Grok escalates or large subagent |

**Grok LOCK shape (per section batch):**

```text
VERDICT: PASS
ENHANCEMENT_1: element + motion + CSS hook
ENHANCEMENT_2: element + motion + CSS hook
FILES: ...
NON_GOALS: ...
```

Composer implements **exactly two** enhancements per section — no third “while we're here.”

---

## 4. Design system (locked for Phase 2)

### Typography (user-approved)

| Role | Font | Token |
|------|------|-------|
| Brand / hero | **Syne** | `--font-brand` (keep) |
| Body / UI | **Space Grotesk** | replace Rajdhani in `--font-body`, `--font-display` |
| Data / labels | **JetBrains Mono** | `--font-mono` (keep) |

**Cleanup:** Remove MI-only **Cabinet Grotesk / Chillax** (`message_intel_feed.html` fontshare link) — one sitewide stack.

**Files:** `templates/base.html` (Google Fonts link), `static/css/base.css` (tokens), grep `Rajdhani` / fontshare in MI partial.

### Color / motion (from subagent brief + `base.css`)

- Accents: `--accent-primary` green, `--accent-blue` cyan, `--accent-orange` amber, `--accent-violet` lilac
- Surfaces: `--card-smoke`, `--card-grain`, `rim-chroma`, `surface-aurora` (reuse — don’t invent fourth gradient family)
- Motion: respect `prefers-reduced-motion`; no new autoplay video

### Conflict surface (touch one subagent at a time)

- `static/js/cockpit_hydrate.js` — hero + proof + deferred panels
- `static/css/ui.css` — new tokens / enhancements
- `static/css/ui-legacy.css` — **avoid broad edits** in Phase 2; override via `ui.css` only
- `templates/partials/premium_cockpit.html` — spine order (rare)
- `server.py` — **do not touch** unless listener flag doc-only

---

## 5. Subagent 0 — Baseline (GATE: no code changes)

**Owner:** Composer  
**Branch:** none (docs only) — this file + STATUS snippet

### Tasks

1. Confirm `git stash list` empty; code changes only on feature branches (local `data/*` dirty is OK — not committed).
2. Record test baseline (see §6).
3. File inventory (see §7) — every later subagent cites paths from here.

### Acceptance

- [ ] This plan committed on `cursor/phase2-baseline-6006` or appended to board
- [ ] Contract guard green
- [ ] Known failure list recorded — **no fixes** in Subagent 0

---

## 6. Test baseline (`main` @ 2026-08-04)

| Suite | Result |
|-------|--------|
| **Contract guard** `tests/test_endpoint_contract.py` | **144 passed** — deploy gate |
| **Full pytest** | **1599 passed**, **73 failed**, 3 skipped |
| **Known / do not fix in Phase 2** | 16× `test_visual_upgrade_polish.py` council h1/h2 + hero-a-tier (tribunal-era markup; tests expect legacy `k3-orb`, not `tribunal-hero`) |
| **Other failures** | Pre-existing monolith/port slices (`server_original`, workers, etc.) — **no new failures** in Phase 2 vs this count |

**Gate for Subagent 6:** full suite pass count ≥ 1599; failures = same 73 baseline (or fewer if unrelated flakes clear); **zero new** failures in touched modules.

---

## 7. File inventory by subagent

### Shared (all subagents)

| Path | Role |
|------|------|
| `templates/base.html` | Fonts, CSS load order |
| `static/css/base.css` | Tokens, typography |
| `static/css/ui.css` | Phase 2 enhancements (prefer here) |
| `templates/partials/premium/scripts.html` | Script load order |
| `static/js/cockpit_hydrate.js` | Home hydrate spine |

### Subagent 1 — Council hero live wire

| Path | Role |
|------|------|
| `templates/partials/premium/tribunal_hero.html` | Hero SSR ring, judges, metrics |
| `templates/partials/premium/council_stage.html` | Dossier wrapper, temporal countdown |
| `internal/preview/tribunal_hero.py` | SSR context builder |
| `static/js/cockpit_hydrate.js` | `patchTribunalRingFill`, judges, metrics, daily-pick patch |

**Audit checklist (Composer):**

- Grep templates/JS for hardcoded demo stats (mockup-only `68.7` etc. — not in prod templates today)
- Ring fill driven from live conviction (`stroke-dashoffset` / `--p` if added)
- Judge weights from `/api/learning/stats` via existing `patchTribunalJudges`
- Stat rail (`tribunal-hero__metrics`) from `patchTribunalMetrics` — verify not static SSR placeholders
- **Sync stamp:** add real `data-synced-at` / footer age from hydrate meta (no fake JS ticker)
- Preserve IDs: `k3-orb-score`, `k3-action-badge`, `tribunal-hero`, `data-testid` from #802

**Grok:** optional — only if layout/IA ambiguous (default: Composer audit-only).

### Subagent 2 — Telegram / Subnet Summers (TOP PRIORITY)

| Path | Role |
|------|------|
| `templates/partials/premium/message_intel_feed.html` | Desk layout, masthead, panels |
| `static/js/message_intel_feed.js` | Hydrate, trending, feed, crowns |
| `static/css/ui.css` + MI rules in `ui-legacy.css` | **Prefer new rules in ui.css** |
| `internal/message_intel/routes.py` | Read-only — verify meta fields, no edits unless bug |

**Grok LOCK required:** 2 visual enhancements (e.g. live mention sparkline strip, sentiment conic gauge, animated feed rows).

**Copy / integration:**

- Remove stale brand refs; align copy with real integration (mentions, proposals, announcements)
- Remove fontshare Cabinet/Chillax — use sitewide stack
- Listener: verify `GET /api/message-intel/status` — if secrets missing, **FLAG in PR body**, do not fake live

### Subagent 3 — Top Picks + Radar

| Path | Role |
|------|------|
| `templates/partials/premium/picks.html` | 1h / 24h horizons (`#section-picks`) |
| `templates/partials/premium/simivision_picks.html` | Weighing room / conviction board |
| `static/js/weighing_room.js` | Weighing room hydrate |
| `static/js/hour_watch_ui.js` | Hour watch UI |
| `templates/partials/premium/radar.html` | Radar view |
| `static/js/cockpit_hydrate.js` | `renderRadar`, hour/day pick paths |

**Grok LOCK:** 2 enhancements × picks section + 2 × radar (can be one Grok pass).

**Mechanical:** Defensive normalize API list vs object shapes; remove dead links (no `/authors` or `/topics` pages — API is `/api/message-intel/authors`).

### Subagent 4 — Market Pulse + Predictions

| Path | Role |
|------|------|
| `templates/partials/premium/pulse_strip.html` | Market pulse ribbon (`#section-market-pulse`) |
| `static/js/market_drivers_ui.js` | Market drivers |
| `static/js/subnet_integrations.js` | Integration bar health |
| `templates/partials/premium/kpi.html` | Prediction backlog KPIs |
| `templates/partials/premium/footer.html` | Footer prediction count |
| `templates/partials/premium/trail.html` | Prediction trail rows |
| `templates/partials/premium/story_strip.html` | Graded prediction chips |

**Grok LOCK:** 2 enhancements × pulse + 2 × predictions/KPI strip.

### Subagent 5 — Social + Homepage health + docs

| Path | Role |
|------|------|
| `templates/partials/premium/social.html` | `#section-social` |
| `static/js/social_sentiment.js` | Social grid hydrate |
| `templates/partials/premium/header.html` | HUD / ops readiness |
| `static/js/ops_readiness_badge.js` | Health / sync badge |
| `static/js/subnet_integrations.js` | “Built on Bittensor” strip |
| `fly.toml`, `DEPLOY.md` | Remove stale scaling / v2 enablement **docs only** |

**Grok LOCK:** 2 enhancements × social trending + 2 × health grid / integrations strip.

**Cross-cutting in SA5:** Font token swap (§4) if not done in SA2.

### Subagent 6 — Integration regression

- Merge order: SA1 → SA2 → SA3 → SA4 → SA5 (or rebase stack)
- Full pytest vs §6 baseline
- Visual consistency pass (dark glass, accent language)

### Subagent 7 — Deploy + live verify

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint
BASE=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh
```

**Live checks:** `/health`, homepage, Telegram desk, thumb dock (390px), hero conviction ring, no placeholder grep on live HTML.

---

## 8. PR cadence (branches)

| Step | Branch pattern | PR title prefix |
|------|----------------|-----------------|
| SA0 | `cursor/phase2-baseline-6006` | docs: Phase 2 baseline |
| SA1 | `cursor/phase2-hero-live-6006` | feat(ui): hero live wire gaps |
| SA2 | `cursor/phase2-telegram-desk-6006` | feat(ui): Telegram desk polish |
| SA3 | `cursor/phase2-picks-radar-6006` | feat(ui): picks + radar polish |
| SA4 | `cursor/phase2-pulse-predictions-6006` | feat(ui): market pulse + predictions |
| SA5 | `cursor/phase2-social-health-6006` | feat(ui): social + health + fonts |
| SA6 | `cursor/phase2-regression-6006` | chore: phase 2 regression (if needed) |

One PR per subagent. **Do not** stack SA2–SA5 in one PR.

---

## 9. Grok prompt template (copy per subagent)

```text
Repo: subnet-dashboard. Subagent N: <name>.
Scope files: <list from §7>.
Design: dark glass, amber/cyan/lime, Syne + Space Grotesk + JetBrains Mono.
Constraints: front-end only; preserve hydrate IDs; two enhancements max; reduced-motion safe.
Current UI: <1 paragraph from live site or template skim>.
Return LOCK: ENHANCEMENT_1, ENHANCEMENT_2, FILES, NON_GOALS. No implementation.
```

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Parallel edits corrupt `cockpit_hydrate.js` | Strict sequential subagents |
| Tribunal vs legacy k3-orb tests fail | Out of scope; don't add new failures |
| MI fontshare vs sitewide fonts | Unify in SA2 or SA5 |
| Listener blocked on Fly secrets | FLAG; honest empty states (#802) |
| `ui-legacy` specificity wars | New rules in `ui.css`; double-class beats legacy |
| Telegram reset + desk warming | 879 msgs / 3d on prod — panels should populate after SA2 polish |

---

## 11. Verification matrix

| SA | Verify |
|----|--------|
| 0 | This doc + contract green |
| 1 | Live hero: ring % + judges update on hydrate; no static metric placeholders |
| 2 | MI desk loads; 2 Grok enhancements visible; no Cabinet/Chillax; listener status documented |
| 3 | `#section-picks` + `#section-radar` render; 4 enhancements total |
| 4 | Pulse ribbon + KPI/prediction surfaces; 4 enhancements |
| 5 | Social + integrations health; Space Grotesk live; dead scaling refs gone from docs |
| 6 | Pytest baseline held |
| 7 | Live fly.dev + 390px glance |

---

## 12. Go order (start here when user says “begin”)

1. **SA0** — commit this plan (Composer)  
2. **SA1** — Composer hero audit/wire (no Grok unless stuck)  
3. **Grok** — SA2 Telegram two enhancements → **Composer** SA2 PR  
4. **Grok** — SA3 picks/radar → **Composer** SA3 PR  
5. **Grok** — SA4 pulse/predictions → **Composer** SA4 PR  
6. **Grok** — SA5 social/health → **Composer** SA5 PR (include font swap)  
7. **SA6** regression → **SA7** deploy verify  

**Do not start SA1 until SA0 is on main.**
