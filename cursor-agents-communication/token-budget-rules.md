# Token budget rules (Pro+ · one agent)

**Audience:** Human + single Cloud Agent + QB  
**Plan:** Cursor **Pro+** (upgraded 2026-07-15)  
**Goal:** Finish §17 UI tail without burning into pay-per-use. Prefer cheap pools; cut context.

## Execution mode

| | Rule |
|--|------|
| **Agents** | **One** primary Cloud Agent only — absorbs former Agent B UI queue |
| **A (`-843d`)** | **Retired** — do not spawn a second Cloud Agent |
| **Grok** | **Subagent** for short DESIGN locks — never run whole agent on Grok |
| **Queue** | **§18** — `s18-automated-build-plan.md` (H1→B1) |
| **Skip** | U4 · U5 unless human explicitly asks |

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

1. **Cost column** shows dollar amounts (e.g. `$0.24`) on new rows — pay-per-use **On-Demand** beyond included Pro+ pool.
2. IDE usage meter shows **>80%** of monthly included API pool with UI tail unfinished.
3. On-Demand spending is enabled and climbing in [billing](https://cursor.com/dashboard/billing).

**Note:** Rows labeled **Free** before upgrade stay Free in history — that is normal. Only **new** runs after Pro+ matter.

## Context cuts

- Read `STATUS.md` + `board.md` + **one** slice from auto-plan — cite other docs by path.
- Scope to `templates/`, `static/`, owned UI paths + contract test if routes change.
- Do not `@`-mention `data/` or `soul_map.json`.
- Obey `.cursorignore` / `.cursorindexingignore` when present.

## Session hygiene

1. **One slice per agent turn** — no drive-by refactors.
2. **No Plan mode every slice** — approved auto-plan is enough.
3. **No second Cloud Agent** — sequential B8→B10 is fine.
4. Prefer short human messages (“continue B8”, “merge”) over re-pasting prompts.
5. Ditto: STATUS post only after merge — not every chat turn.

## Agent prompt add-on (paste once per session)

```
ONE AGENT MODE (Pro+):
- Single Cloud Agent only. Agent A retired — do not spawn a second agent.
- Build with composer-2.5-fast per s18-automated-build-plan.md. Unattended queue H1→B1.
- Grok: subagent only, slow + low/medium. High only after medium FAIL.
- Short Grok LOCK → Composer writes + builds. Skip Grok when auto-plan locks the slice.
- If usage dashboard shows On-Demand $ charges beyond included pool, STOP and tell me.
- Read STATUS.md + s18-automated-build-plan.md only (cite §17 docs by path).
```
