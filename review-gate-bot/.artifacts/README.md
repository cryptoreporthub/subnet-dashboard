# Fix-4 Replit delivery artifacts (PR #1522 evidence)

Evidence-only bundle for freeze replay on Replit `0be6701e`. **Not** a Replit PASS/FAIL verdict.

| File | SHA-256 |
|------|---------|
| `fix4-replit-artifact-bundle-2026-11-07.tar.gz` | `132761ec5697d8b660c99217be1f4c3f124a9e9791c737cd84827520150fbe2e` |

**Pass 5 sync:** inner `sha256sum -c fix4-replit-bundle-2026-11-07.sha256` **pass**; Task 3 patch alone → **666/0**; throw-grid `cad2023a…`; export manifest `565f7544…`.

**Verify after download:**

```bash
sha256sum -c fix4-replit-artifact-bundle-2026-11-07.tar.gz.sha256
tar -tzf fix4-replit-artifact-bundle-2026-11-07.tar.gz | head
```

Inside tarball: `fix4-replit-bundle-2026-11-07/README.md` (ledger table), overlay patch, replay logs, `freeze-tarball.sha256` (upstream freeze `8eea815eb57fdaee87b4bb2c24ff5dad4b88484914d5e088a2ab46249bc8fa87`).

**Replay:** Node **>=22.13**, extract freeze separately, then follow inner README. Node 20 blocks baseline (`tsx`).
