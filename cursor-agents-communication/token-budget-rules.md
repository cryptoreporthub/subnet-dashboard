# Token budget rules (Pro+ · one agent)

**Audience:** Human + single Cloud Agent + QB  
**Plan:** Cursor **Pro+** (upgraded 2026-07-15)  
**Goal:** Finish §18 without burning into pay-per-use. Prefer cheap pools; cut context.

## Execution mode

| | Rule |
|--|------|
| **Agents** | **One** primary Cloud Agent only |
| **A (`-843d`)** | **Retired** — do not spawn a second Cloud Agent |
| **Grok** | **Subagent** for short DESIGN locks — never run whole agent on Grok |
| **Queue** | **§18** — `s18-automated-build-plan.md` (H1→B1) |
| **Skip** | C1 until creds · F7/B12 unless human asks |

## Model pools (cheapest first)

| Work | Use | Avoid |
|------|-----|-------|
| Build / implement / docs / PR | **Composer 2.5** — prefer **`composer-2.5-fast`** | Opus / Sonnet / max Cloud Agent runs |
| Design lock / audit | **Grok slow + low** if narrow; **slow + medium** if DESIGN-marked | Grok **high** / **xhigh** / fast-xhigh as default |
| Escalate | Grok slow + **medium→high** only after FAIL / unsatisfactory | Opening high “just in case” |
| Plan file writing | **Composer** expands Grok’s short LOCK | Grok writing long markdown |

Hard rule: **Grok short LOCK → Composer writes plan + builds** (`grok-lock-composer-write-rule.md`).

## Billing watch (tell the human)

Check [cursor.com/dashboard/usage](https://cursor.com/dashboard/usage) after heavy runs. **Stop and notify the human** if any of:

1. **Cost column** shows dollar amounts on new rows — pay-per-use **On-Demand** beyond included Pro+ pool.
2. IDE usage meter shows **>80%** of monthly included API pool with §18 unfinished.
3. On-Demand spending is enabled and climbing in [billing](https://cursor.com/dashboard/billing).

## Context cuts

- `.cursorignore` + `.cursorindexingignore` — exclude `data/`, `.venv`, caches, binaries, superseded design dumps.
- Read `STATUS.md` + `board.md` + **one** slice from auto-plan — cite other docs by path.
- Scope to owned dirs + contract test if routes change.
- Do not `@`-mention `data/` or `soul_map.json`.

## Session hygiene

1. **One slice per agent turn** — no drive-by refactors.
2. **No Plan mode every slice** — approved auto-plan is enough.
3. **No second Cloud Agent** — sequential §18 queue.
4. **Close stale PRs** (#240 etc.) so agents don’t re-read them.
5. Ditto: STATUS post only after merge — not every chat turn.

## Agent prompt add-on (paste once per session)

```
ONE AGENT MODE (Pro+):
- Single Cloud Agent only. Agent A retired — do not spawn a second agent.
- Build with composer-2.5-fast per s18-automated-build-plan.md. Unattended queue H1→B1.
- Grok: subagent only, slow + low/medium. High only after medium FAIL.
- Obey .cursorignore — do not force-read data/*.json.
- Short Grok LOCK → Composer writes + builds. Skip Grok when auto-plan locks the slice.
- If usage dashboard shows On-Demand $ charges beyond included pool, STOP and tell me.
```
