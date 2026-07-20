# Batch 0 LOCK — Brain presentation architecture

**Status:** REVISED draft for human sign-off (2026-07-20)  
**Revision:** v2 — **keep & elevate** Living Focus + Brain letter (do **not** demote/remove)  
**Batch:** 0 — Brain / mindmap / learning loop presentation  
**Priority:** Rank 1 moat (see `docs/presentation-audit.md`)  
**Viewport:** 390px primary  
**Evidence:** SSR inventory + `/preview/k3-hold` screenshots; `living_focus.js` / `brain_letter.js` capability audit  
**Out of scope:** Engine/logic, Daily Call hero stack redesign, Weighing/Pump polish (Rank 3), full Council/judges Batch 1

---

## Human correction (locked)

> Living Focus and Brain letter are **concepts we want**. The job is not to hide them — it is to make these abstract ideas **feel like a great product**: clear unique jobs, no zombie loading, no restating the Daily Call.

Demote-to-Pro was the wrong fix for overlap. Overlap is fixed by **differentiation**, not deletion.

---

## Verdict (one line)

The brain **exists in pieces** but **does not read as one living loop**. Living Focus and Brain letter already contain the right DNA (judge contention, last learn beat, narrative digest) — they fail because they **re-narrate today’s call** instead of owning a sharper job.

---

## Scorecard (current Batch 0)

| Axis | Score | Note |
|------|-------|------|
| 5-second clarity | 4 | Call is clear on hero |
| Hierarchy | 2 | LF / letter compete with dossier instead of extending it |
| Voice | 3 | Track record OK; “brain UI gate” / warming copy weak |
| Calm authority | 4 | HOLD hero calm |
| Motion & feedback | 2 | Home hydrate → loading zombies |
| Honest-empty | 2 | Multiple “Loading…” shells feel broken |
| **Learning presence** | **2** | Moat not obvious as a spine — buried / duplicated |

**Gate:** Learning presence ≥4 required to close Batch 0.

---

## How abstract concepts become product

Think **roles**, not sections:

| Role | Surface | One job (trader question) |
|------|---------|---------------------------|
| **Decision** | Daily Call dossier | What do I do today? |
| **Microscope** | Living Focus | Who’s fighting over *this* name — and what did we learn last time we graded it? |
| **Briefing** | Brain letter | What’s the one readable story I’d send a friend / open tomorrow morning? |
| **Proof** | What’s working + story strip + paper | Does this system actually get smarter? |
| **Depth** | Pro story path / mindmap / trail | Show me the full chain / graph |

If two surfaces answer the **same** question, one must change its answer — not leave the page.

---

## FINDINGS (ranked)

1. **Living Focus already has a better job than “second dossier”**  
   Code already supports: judge score bars, contention/dissent, weight lean, focus switcher, last HIT/MISS + weight nudge, evidence desk, trail teaser, prove-it CTA.  
   Failure mode: header/sub still read as “council contention on today’s pick” (= dossier), and body starts as `Loading focus from council…`.

2. **Brain letter already has a better job than “third dossier”**  
   Blocks: Today we watch · What the brain learned · Integrity · How we got here + copy/download.  
   Failure mode: “Today we watch” restates the claim; story path duplicates Outcome peel; loading shell feels broken; voice still says “audit gate”.

3. **Track record peel is stats-only; weight-nudge step is hidden**  
   The *loop* beat that Living Focus already renders (`Last learn`) never appears on the default dossier path.

4. **Proof band is a landfill of digests**  
   What’s working → Paper → Weekly → Daily — four “prove it” strips. Weekly/daily should nest; What’s working + story strip should lead.

5. **Mindmap graph stays demoted**  
   Empty Interactive Graph is not Tier‑1. Trail teaser from Living Focus → Market trail is the right handoff.

---

## IA LOCK v2 — keep, differentiate, compose

### Scroll story (Tier‑1 / 2)

```text
Daily Call (decision)
  → Weighing / Pump (ribs — unchanged this batch)
  → Living Focus (microscope — KEEP, reframe)
  → Brain letter (briefing — KEEP, reframe)
  → Proof band: What’s working + Story strip + Paper
  → Letters drawer: Weekly + Daily (collapse)
  → Pro / Market (depth)
```

### Living Focus — KEEP as **Microscope**

**Owns:** judge disagreement on the focused subnet · switch focus across shortlist · last graded beat on *this* SN · prove-it / share / trail teaser.

**Must not own:** restating move/thesis/FLIP (that’s the dossier).

| Change | Spec |
|--------|------|
| Title / sub | `Living Focus` → keep name; sub becomes **`Judge split on the name in focus`** (not “Council contention on today’s pick”) |
| Lead visual | Judge bars + contention line first (already in JS) — make this the hero of the section |
| Learn strip | Promote: **`Last learn`** HIT/MISS + weight nudge is the brain beat — always visible when data exists; honest-empty: `No graded beat on this SN yet — appears after this call resolves.` |
| Switcher | Keep — this is the product magic (focus ≠ only today’s call) |
| Evidence / trail / prove-it | Keep as secondary rows under learn strip |
| SSR empty | Never leave “Loading…” as the calm state — skeleton matching judge bars, then hydrate |

**Relationship to dossier:** Dossier decides; Focus *interrogates* the name (and lets you switch). Opening Focus should feel like zooming in, not reading the call twice.

### Brain letter — KEEP as **Briefing**

**Owns:** one shareable narrative artifact for the day (copy/download stay).

**Must not own:** interactive decision UI, duplicate story-path chrome, third accuracy scoreboard.

| Change | Spec |
|--------|------|
| Section framing | Title stays **Brain letter**; meta: **`Morning brief · graded memory`** (not “Today's narrative · loading…”) |
| Block order (rewrite) | 1) **What changed since yesterday** (learned / weight nudge / signal hits) — lead with learning  
2) **Today’s call in one breath** (short — link/scroll to dossier, don’t rebuild hero)  
3) **Outlook** — one forward sentence (required; see below)  
4) **Integrity** (resolver / expired — trader English)  
5) Drop or collapse **How we got here** (Outcome peel + Pro story path own the chain) |
| Voice | Kill “audit gate” / “waiting for audit gate” → HOLD language matching K3-7 |
| Empty | `Brief writes after the first graded windows land.` |

**Relationship to dossier:** Dossier is the live instrument; letter is the **artifact you’d forward**. Learning leads; call is a short citation; **Outlook** makes the forward pick explicit in prose.

### Outlook — the forward sentence (new, required)

**Clarification:** Today’s Daily Call *is* forward picking — a stance for a resolve window (hours → 24h). What was missing is saying that in plain English once, so the letter doesn’t feel like a recap of the past.

**Owns:** one sentence answering *“What do we think happens next?”*

| Field | Spec |
|-------|------|
| Label | `Next` or `Outlook` (prefer **`Next`** — short) |
| Length | One sentence (≤ ~140 chars). Not a second thesis paragraph. |
| Time anchor | Use real clock when available: `resolves_in` / resolve window (`4h`, `tonight’s close`, `24h window`) — never invent “tonight” if the clock says otherwise |
| Content by stance | **HOLD + candidate:** what must clear before a sized long, timed to the window — e.g. `Over the next 4h we stay flat unless conviction clears 45% and valuation drag eases.`  
| | **LONG:** what we expect by grade — e.g. `Into the next 24h we expect follow-through on the mean-reversion while liquidity holds.`  
| | **No name / quiet desk:** `No sized call this window — watching the desk into resolve.` |
| Source | Compose from existing brief fields (`thesis`/`trigger`/`resolves_in`/`horizon`) — prefer a dedicated `outlook` string from letter builder so hydrate + markdown export stay in sync |
| Must not | Restate full FLIP box; duplicate Track record %; invent price targets |

**Also whisper on dossier (optional, same batch if cheap):** if claim already has FLIP + `LIVE · Nh remaining`, Outlook in the letter is enough. Do **not** add a third forward block on Living Focus.

### Proof band — compose, don’t landfill

| Surface | Decision |
|---------|----------|
| What’s working | **Keep** — lead chips (“signals that predicted price”) |
| Story strip | **Promote from Pro** into proof band — visible graded right/wrong timeline |
| Paper portfolio | **Keep** |
| Weekly + Daily | **Collapse** into Letters `<details>` under the band |

### Dossier spine attachments (still required)

| Surface | Decision |
|---------|----------|
| Trust whisper | **Keep** |
| Outcome peel lifecycle | **Keep** slim chain for *this* call |
| Track record peel | **Enrich** — unhide weight-nudge / show last learn one-liner (can share payload shape with Living Focus learn strip) |

### Pro / Market

| Surface | Decision |
|---------|----------|
| Full story path UI | Stay Pro (deep chain) |
| Living Focus / Brain letter | **Stay on main scroll** |
| Mindmap + Trail | Stay Market; LF trail teaser links in |

### Narrative LOCK

> **“Here’s what we called, how it grades, and how the council changes when we’re wrong.”**

- Dossier = called  
- Living Focus = how judges split + last grade on this name  
- Brain letter = the story of what changed  
- Proof band = the public scoreboard  

---

## COPY LOCK

| Where | After |
|-------|-------|
| Living Focus sub | `Judge split on the name in focus` |
| Living Focus SSR | Skeleton or `Focus opens when judges score this subnet.` — never eternal “Loading focus from council…” |
| Brain letter meta | `Morning brief · graded memory` |
| Brain letter HOLD | Match K3-7 trader voice — no audit-gate phrasing |
| Brain letter Outlook | One timed forward sentence — see Outlook LOCK (e.g. `Over the next 4h we stay flat unless…`) |
| Track record empty nudge | `After resolve, judge weights nudge from this window.` |
| KPI | `brain UI gate` → `Resolver integrity` |
| Story path empty (Pro) | `No audited pick yet — the chain fills when today's call is live.` |

Banned in Tier‑1: `warming up`, `brain UI gate`, `§16`, `audit gate` as drama.

---

## VISUAL LOCK (minimal)

1. Living Focus: judge bars + contention = section hero; learn strip directly under; switcher sticky/secondary.  
2. Brain letter: read like a short letter (prose), not a mini-dashboard of duplicate peels.  
3. Proof band section label e.g. **`What the loop learned`**.  
4. Reuse existing tokens — no new neon system.

---

## IMPLEMENTATION SLICES (after sign-off)

### B0-a — Living Focus product pass (elevate)
1. Reframe title/sub + SSR honest-empty / skeleton  
2. Ensure learn strip + contention lead the render order in `living_focus.js`  
3. Soften overlap: remove any re-stated thesis/FLIP if present; keep action badge + name only as context  
4. Optional preview fixture `/preview/k3-living-focus` for 390px sign-off  

### B0-b — Brain letter product pass (elevate)
1. Reorder blocks: learned → today (short) → **Outlook/Next** → integrity; drop/collapse story-path block  
2. Add `outlook` (or `next`) one-liner in `build_brain_letter()` from call stance + `resolves_in` / horizon + trigger gist  
3. Render + markdown export include the Outlook sentence  
4. Meta + empty + HOLD copy hygiene  
5. Keep copy/download  

### B0-c — Track record peel + proof band
1. Unhide / show weight-nudge line on Track record  
2. Promote story strip into proof band; single include  
3. Collapse weekly + daily into Letters `<details>`  

### B0-d — Copy hygiene + QA
1. KPI rename; kill remaining warming-up on these surfaces  
2. Onboarding tour: add Living Focus + Brain letter steps with new job descriptions  
3. Phone QA 390px  

### Explicitly NOT in Batch 0
- Remove Living Focus or Brain letter  
- Redesign Daily Call claim stack  
- Weighing / Pump polish  
- Promote empty mindmap graph  

---

## Sign-off

- [ ] Human approves **keep & differentiate** (not demote) for Living Focus + Brain letter  
- [ ] Human approves Microscope vs Briefing job split  
- [ ] Human approves slice order B0-a → B0-d  
- [ ] Then Composer implements  

**Suggested reply to unlock build:**  
`LOCK signed v2 — keep LF + brain letter; implement B0-a through B0-d`
