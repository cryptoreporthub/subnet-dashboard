---
description: Use before reporting any finding as new. Check whether the locks, roadmap, docs or code already decided the question, so the review does not re-litigate a settled call.
---

# Settled check

Before you raise a finding, spend one pass asking whether it is already
decided. A review that re-opens a settled question wastes the author's time and
makes the real findings harder to see.

## Where to look, in order

1. **The PR's own body and commits.** The author may have addressed it, or
   recorded why not. A commit message that says "red:" is a test that was
   written to fail first; read it before calling the coverage thin.
2. **The tracking issue.** #1506 for the resolver work, #1479 for the worker
   locks, #1512 for the roadmap, #1461 for do-not-push.
3. **The code.** A guard elsewhere may already make the input unreachable. Grep
   every caller of the function you are about to flag.
4. **The docs.** `docs/`, `DEPLOY.md`, and `cursor-agents-communication/` hold
   decisions that were made deliberately.

## Outcomes

| Outcome | What to write |
| --- | --- |
| Settled, and the diff respects it | one line: `settled by <ref>`, no finding |
| Settled, and the diff breaks it | a finding, citing the decision it breaks |
| Not settled | a finding, and say which decision is missing |

## Do not

- Re-raise a finding whose thread is outdated because the fix landed. Check the
  head, not the comment.
- Treat a passing test as a settled decision. The test is evidence about the
  test.
- Treat a closed PR's discussion as settled unless the decision is in code,
  docs, or the tracking issue.
