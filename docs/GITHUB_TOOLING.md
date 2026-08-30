# GITHUB_TOOLING.md — best-fit libs for

## Merge-path status (live; update on change)

> Maintained by Ditto. This section documents **branch-committed vs merged** state so nothing looks done that isn't. Source of truth = what's on main.

### 2026-08-30 — GO entry committed but NOT PR-merged (write-MCP outage)

- **GO: scope pick-handler occupancy cut** (checklist + constraints) is committed at `8d1eab4` on branch `ditto/go-pick-occupancy-scope-2026-08-30` — **NOT merged to main** as of 2026-08-30 ~01:3xZ.
- Blocked by GitHub MCP transport failure on PR create (write-MCP outage; surfaced separately). Retry with `create_pull_request` when the connection clears, then confirm squash-merge + update this section.
- **Rule going forward:** a GO entry in mission-control-log.md is not "live for Cursor" until it's on main. Branch-committed ≠ merged. If a Go targets a branch, note the branch name here and flip this section to MERGED only after the squash lands.
- Cursor was told to start on the branch state — no code from this GO depends on main; the plan deliverable is a docs/branch item by design.