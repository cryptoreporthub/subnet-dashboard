# CLAUDE.md

Claude-only rules for this repo. Shared rules for all agents are in `AGENTS.md`.
Do not edit `AGENTS.md` from here, because Cursor agents share it.

## Before you call a bug fix done

1. Write a failing regression test first, and run it to see it fail.
2. Make the fix, and run the same test to see it pass.
3. Run `.venv/bin/python scripts/check_invariants.py --check`. It must report 0 new.
4. Run `.venv/bin/python -m pytest tests/test_endpoint_contract.py -q`.

## Before you commit

- Run `python scripts/check_commit_hygiene.py` on the staged index.
- Stage specific files. Never stage `data/` runtime files or `tests/.liveness_allowlist_prev.json`.
- Check the message too: `python scripts/check_commit_hygiene.py --message <file>`.
- A commit message must not name a model identifier. The check allows the exact
  attribution trailer and file names like `CLAUDE.md`.

## Scorer changes

If you touch `internal/council/{state_vector,weights,confidence_calibration,scoring_context}.py`,
stage `data_seeds/score_snapshots.json` in the same commit. See
`.claude/skills/systems-invariants-guard/SKILL.md`.

## Persistence

Do not add a loader that returns an empty container on a corrupt file, in front of a
writer. Fail closed, as `portfolios._load_checked` does.
