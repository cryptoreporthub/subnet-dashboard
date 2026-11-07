# Fix-4 Replit delivery artifacts (PR #1522 evidence)

Evidence-only bundle for freeze replay on Replit `0be6701e`. **Not** a Replit PASS/FAIL verdict.

| File | SHA-256 |
|------|---------|
| `fix4-replit-artifact-bundle-2026-11-07.tar.gz` | `fd397e4bf116ba178288e8c43d2502ebbc4a42ecea67c84a5668bac4ef7e56ec` |

**Pass 5:** inner `check-throw-grid.test.ts` `cad2023a…`; slice (iii)-b ledger **666/0** (Replit MODIFY closure rows A/B).

**Verify after download:**

```bash
sha256sum -c fix4-replit-artifact-bundle-2026-11-07.tar.gz.sha256
tar -tzf fix4-replit-artifact-bundle-2026-11-07.tar.gz | head
```

Inside tarball: `fix4-replit-bundle-2026-11-07/README.md` (ledger table), overlay patch, replay logs, `freeze-tarball.sha256` (upstream freeze `8eea815eb57fdaee87b4bb2c24ff5dad4b88484914d5e088a2ab46249bc8fa87`).

**Replay:** Node **>=22.13**, extract freeze separately, then follow inner README. Node 20 blocks baseline (`tsx`).
