# Cursor Agents Communication

Git mirror of the live coordination board. **Read these files from the repo** — do not rely on Ditto artifacts for STATUS.

## Read order (Cursor Cloud agents + Ditto)

1. **`board.md`** — current STATUS, gates, branches, PRs
2. **`model-guide.md`** — **Composer vs Grok** per phase; when to switch models
3. **`shared-workspace.md`** — handoff order, workspace ready rules
4. **`master-plan-merged.md`** (repo root) — short phase order
5. **`docs/master-plan-merged.md`** — extended contracts (§9 = Phase L)
6. **`ditto-phase-l-handoff.md`** — Ditto: request next phase plans (when active)

Legacy sprint history: **`concurrent-protocol.md`** (J ∥ H-thin — superseded for H-full/L split).

Do **not** use `fetch_memories(["f93f7202"])` for board state this sprint.

## Update after every PR open/merge

Edit **`board.md`** on your branch before merge (or immediate follow-up commit).
