# Presentation audit — path to flagship (presentation only)

**Status:** Living playbook (2026-07-19)  
**Scope:** Visual / IA / copy / states — **not** code quality or engine logic  
**Process:** Grok Chat‑1 LOCK → human sign‑off → Composer build → phone QA 390px  
**Rule:** No implementation PR without a signed LOCK for that batch

---

## Product priority (locked)

Polish order is **not** “whatever looks broken.” Moat first:

| Rank | Layer | Job | Presentation north star |
|------|-------|-----|-------------------------|
| **1** | **Brain / mindmap / learning loop** | Prove the system gets smarter in public | Graded history → weight shifts → narrative feels *alive* and obvious without hunting |
| **2** | **Council + judges** | Who decided, where they disagree | Decision theater with receipts — engine of the call, not admin UI |
| **3** | **Supporting desks** | Weighing, Pump, drawers, tools | Full potential as *ribs*, not co‑heroes |

> Competitors can copy a call card. They cannot copy a visible learning loop.  
> Do **not** spend mainline polish on Rank 3 while Rank 1 still feels bolted on.

### One-line objective

Get the **learning loop** to flagship presentation first (how it shows up *with* every section), then make **council/judges** the clear decision theater on that loop, then bring **Weighing / Pump / tools** up to the same standard as supporting surfaces.

### Spine + ribs

```text
BRAIN SPINE (always in the story)
  signals → judges → council call → resolution → learning update

RIBS (attach to the spine; never replace it)
  Daily Call     = today's vertebra
  Council/Judges = how that vertebra was chosen
  Weighing Room  = candidates still on the table (pre-call)
  Pump           = time-sensitive heat (not the brain)
  Proof band     = graded history / what's working / letters
```

Every rib answers **one** question and may point back to the spine  
(“graded on close”, “weights update after resolve”). Never invent a second brain UI that ignores the first.

---

## What “100%” means

Not pixel‑perfect Figma. Auditable feel:

> A trader opens on phone, feels the **brain is alive**, trusts the **council** as accountable, gets the call in ~5 seconds (HOLD as calm as BUY), peels for receipts when skeptical, and never wonders if the page is broken. Supporting desks feel complete — not rival products.

---

## Scorecard (1–5)

Ship a batch only when it hits **≥4 on every axis**.

| Axis | 1 (bad) | 5 (flagship) |
|------|---------|--------------|
| **5-second clarity** | Confused what matters | Know the call / spine beat instantly |
| **Hierarchy** | Everything same weight | One hero, clear secondary |
| **Voice** | Audit / system language | Trader English |
| **Calm authority** | Alarms, yellow WAIT energy | Confident HOLD reads intentional |
| **Motion & feedback** | Jumpy hydrate, dead taps | Peels / chips / countdown feel alive |
| **Honest-empty** | “Warming up” zombies | Plain context; never feels broken |
| **Learning presence** *(required for Batch 0–1)* | Stats hidden / bolted on | Graded loop obvious; call feels earned |

Track scores per batch over time (Ditto or this file’s score log).

---

## Three passes (never blend)

1. **IA** — order, naming, nav, Tier‑1 / 2 / 3, above/below fold  
2. **Copy** — headlines, strips, peel bodies, micro‑labels  
3. **Visual** — type, spacing, color semantics, chips, rings, chevrons  

Same shell can stay; re‑rank what’s loud (K3‑7 pattern).

---

## Audit batches

### Batch 0 — Brain presentation architecture *(FIRST)*

**Question:** Where does the learning loop live in the scroll story, and how does every Tier‑1 section point at it?

**Surfaces (audit as one composition):**

| Surface | Role today (approx.) | Audit ask |
|---------|----------------------|-----------|
| Daily Call Learning peel | Stats + lifecycle | Is this the brain’s front door or a stub? |
| Story path / lifecycle | Thin / Pro‑adjacent | Promote, restyle, or absorb? |
| Brain letter | Often loading | Tier‑1 narrative or demote? |
| What’s working | Proof chips | Part of proof band or orphan? |
| Daily recap / weekly letter / paper portfolio | Proof band | One coherent “we learn” strip? |
| Mindmap / trail | Drawer / graph | Evidence depth or demoted correctly? |

**Required LOCK outputs:**

1. **IA LOCK** — Tier‑1 (always visible) vs Tier‑2 (proof) vs Tier‑3 (Pro); kill duplicate loading narratives that compete with the dossier  
2. **Narrative LOCK** — one trader sentence: *“Here’s what we called, how it graded, and how the council changed.”*  
3. **Handoff rules** — how Council → Weighing → Pump *reference* the brain without restating it  

**Sign-off gate:** Learning presence ≥4 and no competing “second brain” sections above the fold.

Until Batch 0 is signed, Rank‑3 polish is not the mainline.

---

### Batch 1 — Council + judges

**Question:** Does the judge layer feel like the engine of the call, or like admin UI?

- Claim / Evidence / Council votes peels  
- Judge cards / weights (promote what must be seen; Pro for depth)  
- Disagreement as a feature (split votes, track record)

Council is **presentation of the brain’s decision theater** — not a product above the learning loop.

---

### Batch 2 — Supporting desks to full potential

Only after Batches 0–1 score well:

- Weighing Room (peel receipts; continuity with brain language)  
- Pump lane (predictive voice; handoff from Weighing)  
- Market / Pro drawers as honest demotion, not abandoned UI  

---

## Journey checklist (390px)

Audit by **scroll story**, not by CSS file. Use preview fixtures when possible  
(`/preview/k3-hold`, pump previews; extend fixtures as needed).

| Journey | Surfaces | Pass question |
|---------|----------|---------------|
| **Brain spine** | Learning peel, story path, proof band, letters | Is the loop obvious? |
| **Morning open** | Daily Call hero + peels | What do I do in 5s? |
| **Council engine** | Judges / votes / disagreement | Do I trust who decided? |
| **Bench** | Weighing Room | Who’s next without ranks? |
| **Heat** | Pump chip + desk | Predictive or lagging? |
| **Depth** | Pro + Market drawers | Demoted, not abandoned? |

### States matrix (per surface)

Screenshot: SSR first paint · post‑hydrate · empty · live countdown · resolved/graded.  
Most of the last 20% of polish is **state polish**.

---

## Design contract (minimal, enforceable)

Start small; expand only from audit findings:

1. One type scale: hero / section / body / whisper  
2. Three conviction tones: go / hold / caution — no rogue alarm yellow on HOLD  
3. Shared section‑label pattern (e.g. “Council is weighing” style)  
4. Peel pattern: label → one sentence → optional grid  
5. No internal nouns in Tier‑1 copy (audit gate, publish, council scan as drama…)  
6. Max one kicker line per card face  
7. ≥44px tap targets on mobile  
8. No duplicate information above the fold  
9. Every Tier‑1 rib may whisper the spine once — never invent a parallel brain  
10. `prefers-reduced-motion` respected for rings / chips / countdown  

---

## Workflow

```text
You:      Pick batch + 3–5 screenshots (390px, prod or preview)
Grok:     Presentation audit → FINDINGS + LOCK (no code)
You:      Sign LOCK (or redline)
Composer: Minimal diff + preview route if needed
You:      Phone QA on preview → merge
```

### Grok Chat‑1 prompt (paste)

```text
You are K3 design for SimiVision subnet-dashboard.
PRESENTATION ONLY — no code, no engine logic.

PRIORITY (locked):
1) Brain / mindmap / learning loop (moat)
2) Council + judges (decision theater)
3) Supporting desks (Weighing, Pump, tools) — ribs only

Batch: [0 Brain | 1 Council | 2 Desks — name the surfaces]
Screenshots attached: [list]
Viewport: 390px primary

Return:
1. FINDINGS — ranked by impact on Learning presence / hierarchy / voice
2. IA — Tier-1 / 2 / 3 recommendations (spine + ribs)
3. COPY — trader English rewrites (before → after)
4. VISUAL — only if IA+copy are clear
5. LOCK — implementable bullets Composer can build without inventing
6. OUT OF SCOPE — explicitly defer Rank-3 if this is Batch 0/1

Do not redesign the Daily Call hero stack unless this batch is about it
and the LOCK says so. Prefer re-ranking what’s loud over new shells.
```

---

## Score log

| Date | Batch | Axes (min) | Notes | LOCK signed? |
|------|-------|------------|-------|--------------|
| — | 0 Brain | — | Next | — |
| — | 1 Council | — | After 0 | — |
| — | 2 Desks | — | After 0–1 | — |

---

## Related

- North star: `docs/K3-Master-Architecture-V2.md` §1  
- Hero voice: `cursor-agents-communication/k3-7-k3-vision.md`  
- Board queue: `cursor-agents-communication/board.md`  
- Live coordination: Ditto `Cursor Agents Communication`
