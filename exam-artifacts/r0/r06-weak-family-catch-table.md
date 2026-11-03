# R0.6a — weak planted families vs instruction state (no new model runs)

Sources: `exam-artifacts/r0/r23-full-63-post.json` scored with score-v2 (**first `posted:true` only**); r21 store exams; commit messages for r4–r6 instruction bundles.

| Round | Instruction state (bot prompt) | blank-reload catch/n | nonowner-refresh catch/n | root-filter catch/n | Notes |
|-------|--------------------------------|----------------------|--------------------------|---------------------|-------|
| r23 full-63 | PR-head `50e231f3` instructions (~6813 B file; 6790 trimmed) — **no** owner-rules / reviewer-state blocks | 0/3 | 0/3 | 1/3 | Pinned stack for r21–r27 per review |
| r21 pre63-pre2 (store) | PR-head era | ~0–1/3 per slot | ~0/3 | mixed | See `internal/handoff-2026-10-31/pr-1522-r21/` transcripts |
| r4 (`4002a91`) | + owner-rules block + reviewer-state block in instructions | **N/A** (no r23 pooled JSON on origin) | **N/A** | **N/A** | Hard-exam r4 bundle local-only; use R2 arm **D** as structural proxy |
| r5 (`3130f3b`) | + verdict guards / skill-not-read step | **N/A** | **N/A** | **N/A** | Local harness only; guards live in `bot/instructions.ts` append, not re-scored here |
| r6 (`8764c29` / `d8751f9`) | Ported guards (local only) | **N/A** | **N/A** | **N/A** | Never merged to PR #1522 head; see `r06-model-config-unverified.md` for effort field |

**R2 arms (this branch):** base = PR head only; B = +owner rules (4002a91 verbatim block); C = +three skills; D = B + reviewer-state. SHA256/chars in `exam-artifacts/r0/instructions-variants.json`.
