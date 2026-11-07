# Fix-4 Replit delivery artifacts (PR #1522 evidence)

Evidence-only bundle for freeze replay on Replit `0be6701e`. **Not** a Replit PASS/FAIL verdict.

| File | SHA-256 |
|------|---------|
| `fix4-replit-artifact-bundle-2026-11-07.tar.gz` | `40bd4561740e6d9a1345e5df66c94782f869cf41ad77d42e5b163fd53bc3eb0b` |

**Verify after download:**

```bash
sha256sum -c fix4-replit-artifact-bundle-2026-11-07.tar.gz.sha256
tar -tzf fix4-replit-artifact-bundle-2026-11-07.tar.gz | head
```

Inside tarball: `fix4-replit-bundle-2026-11-07/README.md` (ledger table), overlay patch, replay logs, `freeze-tarball.sha256` (upstream freeze `8eea815eb57fdaee87b4bb2c24ff5dad4b88484914d5e088a2ab46249bc8fa87`).

**Replay:** Node **>=22.13**, extract freeze separately, then follow inner README. Node 20 blocks baseline (`tsx`).
