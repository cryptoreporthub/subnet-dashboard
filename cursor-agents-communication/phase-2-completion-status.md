# Phase 2 — completion status

**Completed:** 2026-08-04  
**main:** post-#809 (`cursor/phase2-social-health-6006`)

## PRs merged (SA0–SA5)

| PR | Subagent | Summary |
|----|----------|---------|
| #804 | SA0 | Execution plan |
| #805 | SA1 | Tribunal hero sync stamp + ring `--p` |
| #806 | SA2 | Telegram desk gauge + feed motion |
| #807 | SA3 | Picks reveal + radar frame |
| #808 | SA4 | Pulse halo + KPI gauge + story strip |
| #809 | SA5 | Social cards + ops HUD + Space Grotesk |

## SA6 — regression gate

| Metric | Baseline (plan §6) | Post Phase 2 |
|--------|-------------------|--------------|
| Contract guard | 144 passed | **144 passed** |
| Phase 2 module tests | — | **155 passed** (`tests/test_phase2_*.py` + contract) |
| Full pytest | 1599 passed, **73 failed** | **1615 passed**, **72 failed**, 3 skipped |

Gate: pass count ≥ 1599 ✓ · failures ≤ 73 ✓ · no new failures in Phase 2 touch modules ✓

Known remaining failures (do not fix in Phase 2): `test_visual_upgrade_polish.py` tribunal-era council h1/h2 + hero-a-tier; monolith/port slices (`server_original`, workers, etc.).

## SA7 — deploy + live verify

- Fly Deploy on `main` after #809: **success**
- `BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint` → **OK**
- `babysit_phase.sh la` (hero API + SSR hooks) → **OK**
- `babysit_phase.sh lb` (integrations + pulse rail) → **OK**

Live HTML markers (post-deploy): `tribunal-hero`, `tribunal-hero-sync`, `Space+Grotesk`, `sr-pulse__breadth-halo`, `pick-card--reveal`, `soc-card--enter`, `kpi--accuracy-gauge`, `ops-readiness-badge`.

## Explicitly deferred → Phase 3

- Full `ui-legacy.css` purge
- Fix `test_council_stage_h1/h2_*` / hero-a-tier tests (tribunal markup drift)
- Tranche 2 glow/token sweep beyond Phase 2 LOCK enhancements

## Preview URLs (prod)

- Hero / council: https://subnet-dashboard.fly.dev/#section-daily-pick
- Telegram: https://subnet-dashboard.fly.dev/#section-message-intel
- Picks: https://subnet-dashboard.fly.dev/#section-picks
- Radar: https://subnet-dashboard.fly.dev/#section-radar
- Pulse: https://subnet-dashboard.fly.dev/#section-market-pulse
- KPI: https://subnet-dashboard.fly.dev/#section-kpi
- Social: https://subnet-dashboard.fly.dev/#section-social
