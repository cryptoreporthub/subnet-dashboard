@AGENTS.md

# CLAUDE.md — Claude Code overrides

`AGENTS.md` was written for Cursor agents. Where it conflicts with this file, this file wins for Claude Code sessions.

## Mapping from Cursor config

| Cursor | Claude Code equivalent |
|--------|------------------------|
| `.cursor/rules/ponytail.mdc` | Section "Ponytail" below |
| `.cursor/rules/fly-mcp.mdc` | Section "Fly guardrails" below |
| `.cursor/rules/ditto-sync.mdc` | Section "Ditto" below |
| `.cursor/rules/subagent-models.mdc` | Not applicable: Grok/Composer/Luna slugs don't exist here. Use `.claude/agents/` (`architect`, `pr-review`). Keep the rule: subagents don't edit product code unless asked. |
| `.cursor/mcp.json` | `.mcp.json` (not yet ported, needs the owner's approval) |
| `~/.cursor/projects/<slug>/agent-transcripts/<uuid>/<uuid>.jsonl` | `~/.claude/projects/<slug>/<uuid>.jsonl`, slug = abs path with `/` → `-` (leading dash kept) |
| `.cursor/skills/` | `.claude/skills/` |

## Fresh worker bootstrap
Cloud workers have no `.venv` and no pytest. Run `bash scripts/claude-session-start.sh` (creates `.venv`, installs deps + pytest + httpx, installs pstack skills at a pinned SHA). Python on the worker may be 3.13; the contract tests pass there.

## Verification
Use `.claude/skills/verify-subnet-dashboard/`. Test runs write to `data/*.json`; do not commit those. Restore them before finishing.

## Review discipline
Review at the pinned **head** SHA and note the **base** SHA. Post PASS/BLOCK/MODIFY with pytest output and an explicit unverified list. No merge, no deploy without an explicit ask. Draft PRs stay draft.

## Ponytail
YAGNI, minimal diff. Reuse existing helpers before writing new ones; stdlib and installed deps before new ones. Fix root cause (grep every caller). Never cut validation, security, error handling, or contract-test coverage. Mark deliberate simplifications with a `ponytail:` comment naming the ceiling.

## Fly guardrails
Read-first: status, logs, machine list. Get explicit approval before `fly deploy`, machine destroy/restart, secrets, volumes, or `fly.toml` VM/process changes. Don't bump the daily-pick 90s timeout or unmute `LOOP_STALL_GUARD_KILL` unasked. No "should work": state the command and the verification.

## Ditto
Ditto tools are `mcp__Ditto__*` (deferred; load with ToolSearch). At task start search the subject "Subnet Dashboard Service". Write back only meaningful status or decisions, and mirror them in `cursor-agents-communication/mission-control-log.md`. Don't use the `f93f7202` board gating from `AGENTS.md` as a blocker if the tool is unavailable; say so instead.

## pstack skills
Installed to `~/.claude/skills` by `scripts/install-pstack.sh` (source: github.com/cursor/plugins, pinned SHA inside the script). `/recall` reads Claude transcripts after the path rewrite.
