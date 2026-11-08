# Fix-4 Replit delivery artifacts (PR #1522 evidence)

Evidence-only bundle for freeze replay on Replit `0be6701e`. **Not** a Replit PASS/FAIL verdict.

| File | SHA-256 |
|------|---------|
| `fix4-replit-artifact-bundle-2026-11-07.tar.gz` | **1ec3c4aa…* |

**Pass 6:** Task 3 patch `5f70caca…` applies export manifest `565f7544…` + overlay `0ffcdb6f…`; apply-only **666/0**. Inner `sha256sum -c` **17/17**.

**Verify after download:**

```bash
sha256sum -c fix4-replit-artifact-bundle-2026-11-07.tar.gz.sha256
tar -xzf fix4-replit-artifact-bundle-2026-11-07.tar.gz
(cd fix4-replit-bundle-2026-11-07 && sha256sum -c fix4-replit-bundle-2026-11-07.sha256)
```

**Replay:** Node **>=22.13**, extract freeze `8eea815e…`, `git apply -p1 fix4-task3-export.patch`, `npm ci && npm run check && npm test`.
