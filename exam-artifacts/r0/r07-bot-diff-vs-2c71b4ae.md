# R0.7 — `review-gate-bot/bot/` vs PR #1522 head `2c71b4ae`

**Branch:** `cursor/r1-base-harness` (Joshua GO: Composer 2.5 `fast:false` at `2c71b4aeea36bfde42ca756f65e3168c84123e68`)  
**Compare:** `git diff 2c71b4aeea36bfde42ca756f65e3168c84123e68 HEAD -- review-gate-bot/bot/`

Eval-only harness port (no production redact/post_verdict refusal stack from R0).

| Path | Change | Purpose |
|------|--------|---------|
| `bot/instructions.ts` | **new** | SDK `defineInstructions`; arm **A** append empty → byte-identical to `instructions.md` |
| `bot/lib/eval-repo-fixture.ts` | **new** | Eval base read/list semantics (`baseFiles` + unchanged `files`) |
| `bot/lib/eval-verdict-once.ts` | **new** | Eval `post_verdict` accepts once per session (`posted:true`) |
| `bot/lib/fixtures.ts` | +`RepoFixture.baseFiles` | Fixture loader typing |
| `bot/lib/instruction-blocks.ts` | **new** | R2 arms B/D verbatim blocks (exam only via `R2_METHOD_ARM`) |
| `bot/lib/method-variants.ts` | **new** | Arms A–D; default **A** |
| `bot/lib/review-method.ts` | **new** | Arm C skill inlining helpers (exam arms) |
| `bot/tools/read_repo_file.ts` | eval branch | Uses `evalRepoTextAtBase` |
| `bot/tools/list_repo_files.ts` | eval branch | Uses `evalRepoPathsAtBase` |
| `bot/tools/compare_suite_runs.ts` | eval branch | Reads `gate.json` suite pin (`clean` → fixture clean) |
| `bot/tools/post_verdict.ts` | eval branch only | `eval-verdict-once` (live path unchanged vs `2c71b4ae`) |
| `bot/agent.ts` | **unchanged** | Still `composer-2.5` + `fast:false` |
| `bot/lib/redact.ts` | **unchanged** | No R0 scrubber expansion |

**Not merged to #1522.** No R1-BASE model eval until RUN-READY.
