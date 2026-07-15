# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T05:52:00Z  
**main:** `ce324d7` — **N/O + P complete; P5 verified on prod**

## One-line

**Prod live with flags on. Backtest 53.5% (+ lift). P4 DNS blocked on Fly/registrar auth.**

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| N/O + Phase P | **#227** · **#228** · **#232** |
| Board hygiene | **#229**–**#234** · **#236** |

## Phase P — COMPLETE + verified

- Prod flags: **on** (auto-retrain, conviction alerts)
- P5 backtest: council/oracle **53.5%**; oracle ≥0.55 bin **69.8%** — no N1 reopen
- `./scripts/verify_prod.sh` for post-deploy checks
- **P4 pending:** `dashboard.cryptoreporthub.com` — needs `flyctl auth` + registrar CNAME (`DEPLOY.md`)

## Next

- **Human:** `flyctl auth login` → `flyctl certs add dashboard.cryptoreporthub.com` → CNAME at registrar
- **Monitor:** `./scripts/verify_prod.sh` after deploys
- Ditto defines next roadmap slice (`master-plan-merged.md` §16)
