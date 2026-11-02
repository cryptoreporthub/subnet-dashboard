# r23 bars-lock evidence (before baseline-A 2026-11-02T18:51:54Z)

## Timestamped record found

| Source | Timestamp (UTC) | Content |
|--------|-----------------|--------|
| `/cursor/stores/self/docs/pr-1522-r23-plan-v5.3.md` §6 | **file mtime 2026-11-02T18:41:17Z** | Option B only; GO if rank-2 false-PASS ≤4/12 (no pack sum=3); inconclusive 5–6 with optional extra batch; pooled ≤8/24; NO-GO ≥7 or any pack=3 |

## Not timestamped before baseline-A

| Source | Finding |
|--------|---------|
| Git commits on exam stack | `23bd34f0` / `a5819378` committed **2026-11-02T18:51:24Z** (30s before baseline-A); commit messages do not restate numeric bars |
| PR #1544 comments | First bars text in **6589989052** at **2026-11-02T22:23:24Z** (after all packs) |
| `internal/handoff-2026-10-31/pr-1522-r23/progress.log` | Header line 2 says "Option B only" but no `BARS=` line; "Option B only — A rejected" appears **after** baseline-C (line 25, ~19:04Z). File lacks per-line timestamps → **stated-not-evidenced** as a bars lock before first pack except via cross-reference to plan §6 mtime above |
| `exam-artifacts/r23/PINS.md` @ publish | No bars table at exam run time |

## Conclusion

Bars numerics were **written in plan v5.3 §6 at 18:41:17Z** on the exam machine store. They were **not** mirrored in a git commit or PR comment before baseline-A started. Exam execution relied on that plan/handoff text; this artifact documents both the 18:41:17Z file and the gaps.
