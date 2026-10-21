# Subnet Dashboard Audit — Master Packet · 2026-10-18

**Repository:** `cryptoreporthub/subnet-dashboard`
**Pin (all code claims):** `3a65d34ac46a28395559310f21db013b4581c645`
**Session:** 2026-10-18 · **Status:** proposals and findings only. Nothing committed, nothing pushed, no branch cut, no production change.

> **This is the single file.** It contains everything produced today: the spec, the cap audit (Rev 3), the Tier 2 instrumentation audit, the scoring-universe design pass, the calibration-window design pass, the Telegram scope-lock decision record, and the Telegram bleed audit with today's live probes. The separate files are superseded and need not be read. Where they disagree, **Part VIII** says which one wins and why.

> **Line numbers.** Every line number here is a **file offset at the SHA named beside it** — never a line in a downloaded copy. Raw-GitHub copies carry a five-line header, and that is what produced every wrong number in Parts VI–VIII; they are corrected. The single authoritative Telegram line map is **VIII.1**. The "earlier claim → now" tables now live in **Part X** (Part II §0 carries its own revision history); read them as provenance, never as guidance.

## Rev 5 correction block (2026-10-20, docs only; amended 2026-10-21)

Checked against the pin `3a65d34a` by an independent review (Ditto, 2026-10-20). No product code changed. The body of §2, §3 and §6 is renumbered to these values. This block stays as the record of what changed. Amended 2026-10-21: three length counts below were wrong (`scoring_cap.py` is 121, `calibration.py` is 296, and the test files are 86 and 63), and the corrected values are in place.

**Anchors that are off by +5**

- Most Rev 3 line numbers in §2, §3 and §6 are five lines high. Offsets vary by row, so the correction table gives the actual value for each one. The §2a table holds the right values. Correct values: `fly.toml` 89–93 (not 94–98); `server.py` `TOP_SCORING_UNIVERSE` 647 (not 652); `_cap_subnets_for_scoring` 925–932 (not 930–937); the shell cap at 1066 and the hourly cap at 3363 (not 1071 and 3368); `score_snapshots.py` `_snapshot_subnet_cap()` 45–60 and its call site 667–676 (not 672–681); `pick_scheduler.py` `_load_capped_subnets` 151–161; `pick_selection_audit.py` `_scheduler_cap_limit` 57–60; `daily_pick_engine.py` `_subnets_for_pick_creation` from 205.
- Suspected cause, not verified: raw read output may start with a five-line header (Title, blank, URL Source, blank, Markdown Content). If so, numbering raw output would shift every citation by +5.
- The cap-site table rows are at 1925–1932 and the door table rows at 2830–2835. The earlier pointers, 1883–1888 and 2788–2789, land on other content.
- §6 cites `pick_selection_audit.py` lines 55–80. The cap assignments are at 57–60 and the docstring claim is at line 6.
- Correct at the pin: `score_snapshots.py:263-268` (`_key`) and `state_vector.py:1893` (calibration block).

**Premises that are wrong or incomplete**

- `TOP_SCORING_UNIVERSE` has three raw-env readers, not two: `server.py:647` (default 20), `daily_pick_engine.py` near 210 (default 40), and `pick_selection_audit.py:57–60` (default 40). `score_snapshots.py:45–60` is a fourth. In worker mode it falls back to `TOP_SCORING_UNIVERSE` with default 40. Its module constant at `:38` defaults to 0.
- So "0 or 40" describes the deployed value (`fly.toml:89` = 40), not the code default. Changing the `TOP_SCORING_UNIVERSE` default touches more than one site.
- Neither `TOP_SCORING_UNIVERSE` nor `PICK_SCHEDULER_UNIVERSE_CAP` is declared in `fly.toml`. Whether Fly secrets override them is unverified.
- This collision is already tracked in `cursor-agents-communication/audit-kit/findings/C9-TOP-SCORING-UNIVERSE-001.json` and `queue/done/C-016.json`. Check their dispositions before treating it as new.
- §4: the 200-row comment in `engine.py` is stale. `engine.py:397-399` documents the deliberate raise to 5,000 rows. This is a stale comment, not a regression.
- "37 `source: none` at 129 and 131 to 167" lists 38 values. The real set is 129, 131, and 133–167 (37). Netuids 130 and 132 have no row.
- `expected_netuids` does not exist in `/api/learning/health`. Cite `membership_expected_count == membership_admitted_count == 165` from the timing block instead.
- §7.3's "~7,471×" does not reproduce from its printed operands (61.745 / 0.0083 ≈ 7,439). Print the unrounded operands or drop the ratio.
- The table of contents lists Part IX twice. Remove the second row.

**Not corrected here**

- The same-process claim in §7.6 is false at the pin. The worker is a second process, so its metrics do not reach web `/metrics`. §7.6, §5.4 and the scorecard row 7 carry the correction. The Fix A premise is checked in §10.1.
- Every `/metrics` reading in Part III §7 is a scrape-time value. The code that produces it is verified; the readings are not.
- The review verdict is KEEP with one condition: §2, §3 and §6 must be renumbered before §3 is used as an edit list. This block is the interim fix.

## How to read this

| Part | What it answers | Originally |
|---|---|---|
| **I** | What was decided about the scoring universe, and the change list | `specs/full-universe-scoring.md` |
| **II** | Why the cap should die: receipts R1–R12, the verdict document audited H1–H10, gaps, fence | Rev 3, via `packets/full-universe-scoring-claude.md` |
| **III** | What the system actually does at runtime: instrumentation map, production measurements, four fixes A–D | `tier2-instrumentation-audit.md` |
| **IV** | The design pass the audit never had: eight selection sites, four defaults, three candidate shapes, the `Selection`/`ScoringBudget` contract | `scoring-universe-contract-2026-10-18.md` |
| **V** | What the 3,000-row scan should become: the two clocks, the window bias, the `Window` type | `calibration-window-contract-2026-10-18.md` |
| **VI** | The decision: Telegram comes out of scoring, capability deleted, not bounded | `audit-telegram-scope-lock-2026-10-18.md` |
| **VII** | The bleed sites verified at both SHAs, today's live probes, and the corrected fix order | `telegram-bleed-audit-2026-10-18.md` |
| **VIII** | **Reconciliation** — every contradiction between Parts I–VII, with a ruling | new |
| **IX** | What is still unverified, ordered by what would change a decision fastest | new |
| **X** | **Provenance appendix** — every claim that moved, every retired line number. Not guidance | new |

Part numbering is deliberate: each part keeps the section numbers it was written with (`§2a`, `R5`, `H10`, `§10.3`), because those numbers are quoted in review. A bare `§n` means *inside the part you are reading*.

## Two SHAs, and why it matters

| Role | SHA | Date (UTC) | Evidence |
|---|---|---|---|
| **PIN** — everything audited | `3a65d34ac46a28395559310f21db013b4581c645` | 2026-10-18T00:59:45Z | GitHub commit API |
| **PROD** — what is live | `357980b43f374ca9bf109380a7229afab0c77643` | 2026-10-17T16:00:40Z | `/version` on subnet-dashboard.fly.dev |

**PROD is 6 commits behind PIN.** Between them, oldest first: `ef234c95` (docs vehicle) → `61d49f3f` (top-picks from snapshot) → `49faea95` (**adds `internal/council/scoring_context.py`**) → `bb4ce004` (per-build cost counters) → `cd0c7b94` (profile hoist, parallel build) → `3a65d34a` (cost counters #1458).

Consequence: **the file under audit is ahead of the process running it.** The hoist does not exist in production at all, and the counters that would measure the Telegram bleed are on main and undeployed. Parts II–VI were written against PIN; Part VII checks the same claims against PROD and reports both.

## Standing constraints

- **No commits. No pushes. No branches.** Every fix in this packet is a proposal.
- **Telegram stays out of the scoring path.** It is a consumer of decisions, not a participant in the loop that makes them.
- **Citations must name a SHA.** Line numbers drift between commits and between extraction methods; Part VIII §1 keeps the authoritative table.
- **Where a document said "unverified," it still says so** — Part IX is the list, and it is not padded with things that were settled.

---

## Part I — Spec: full-universe scoring

Pinned at `3a65d34a`. Branch name `feat/full-universe-scoring` is **proposed only — not created**. Nothing is cut, committed, or deployed.

### Decisions (locked)
1. **No universe cap.** Every subnet in the universe is scored every cycle.
2. **No hunt band.** `scoring_cap.py` is deleted, not tuned. Mega / mid rank tiers, `mega_ceiling_rank`, `mid_rank_min`, `mid_rank_max` all gone.
3. **Telegram evidence leaves scoring entirely.** Message-intel ingestion/rollup stays as a product feature; it no longer touches a council score.
4. Any remaining compute limit must be an **explicit, observable budget** that marks rows `scored: false, reason: "budget"` — never a silent truncation, never an unwritten row.

### Why (evidence)
| Finding | Location | Effect |
|---|---|---|
| `calibration_for_subnet` loops **all** conviction rows per subnet, `classify_call()` + `_parse_ts()` before the netuid check | `internal/message_intel/calibration.py` | ≈ 127 × 3,000 ≈ 380k calls/cycle |
| Called unconditionally from scoring | `internal/council/state_vector.py:1900` | paid for every subnet |
| `TELEGRAM_EVIDENCE_CALIBRATION` set in **no** fly toml | `fly.toml`, `fly.worker-v2.toml`, `fly.worker-v2-essential-soak.toml` | `enabled` false → `adjustment_points` always `0.0` |
| ⇒ the scan currently has **zero** score effect | — | pure waste, and the reason a 40-cap "felt" necessary |
| `scenario_outcome_adjustment` scans 300 scenarios per subnet | `internal/council/memory_scoring.py` | same anti-pattern, 10× smaller |
| 40-cap has two defaults and one borrowed from another knob | `score_snapshots.py:38` vs `45-60` | `SCORE_SNAPSHOT_MAX_SUBNETS=""` → 40; unset+worker → `TOP_SCORING_UNIVERSE` |
| `TOP_SCORING_UNIVERSE` has three defaults | `server.py` 20, `pick_selection_audit.py` 40, `score_snapshots.py` 40 | unreason-able |

### Changes
1. **Delete** `internal/subnets/scoring_cap.py`.
2. **Remove all call sites**: `server.py` (`_cap_subnets_for_scoring`, `TOP_SCORING_UNIVERSE`), `internal/council/pick_scheduler.py`, `internal/council/daily_pick_engine.py`, `internal/council/pick_selection_audit.py`, `internal/council/score_snapshots.py` (the `cap > 0` block, `capped_out`, `selection_policy = "rank_cap"`).
3. **`score_snapshots.py`**: delete `_snapshot_subnet_cap()` and its `is_worker_mode() → TOP_SCORING_UNIVERSE` fallback. One env, `SCORE_SNAPSHOT_MAX_SUBNETS`, default `0` = full universe. Module constant and function must agree — there is only one function now.
4. **`scoring_context.py`**: drop `telegram_conviction_rows` and `telegram_calibration_health` from `enrich_scoring_market_context`. Build `scenario_memory_by_netuid` once per batch instead.
5. **`state_vector.py`**: delete the telegram calibration block and the `telegram_evidence_calibration` output field.
6. **Delete** `internal/message_intel/calibration.py`, `engine.telegram_calibration_status`, `routes.api_message_intel_calibration`, `tests/test_telegram_evidence_calibration.py`. Keep `rollup.py` and `proof.py`.
7. **`memory_scoring.scenario_outcome_adjustment`**: consume `scenario_memory_by_netuid` — one grouping pass instead of a 300-item scan per name. Keep the ±2 pt tilt.
8. **fly tomls (3)**: delete `SCORE_SNAPSHOT_MAX_SUBNETS`, `SCORING_CAP_MEGA_CEILING_RANK`, `SCORING_CAP_MID_RANK_MIN`, `SCORING_CAP_MID_RANK_MAX`. Pin `SCORE_SNAPSHOT_SCORE_WORKERS = "2"` explicitly.

### Invariants to test
- `build_snapshot` with N subnets returns **N** rows — no truncation at any N.
- Coverage is computed against the **universe**, so `coverage_complete` is falsifiable.
- Removing telegram changes no score by more than 0.0 (assert adjustments were already 0).
- No module imports `scoring_cap`.

---

## Part II — Audit packet: killing the caps (Rev 3)

```
TASK:  Remove arbitrary universe caps and heuristic filters from scoring, and remove
       Telegram evidence from the scoring path. Full universe, measured not assumed.
TIER:  3 — score 9 (files 2 + core loop 2 + persisted writes 2 + fly.toml direct 2 + reversibility 1)
BASE:  main @ 3a65d34ac46a28395559310f21db013b4581c645
FENCE: no push / no merge / no deploy / no fly-deploy
SCOPE: see §3 — exhaustive
GAPS:  see §6 — stated as unobserved
```

Rev 3. Frozen at send. Findings back as a numbered list, not a rewritten packet.

---

### §0 — Revision history, and what you should distrust

**Rev 1** was written from a decoding path that wrote literal `\n` escape sequences into my
scratch copies. Every `fly*.toml` line number in it was junk.

**Rev 2** re-derived those, added two missed caps and five missed files, and — the part
that matters — **withdrew the packet's central performance assertion**, because the
repository's own `docs/agent-friendly/scoring-caps-verdict.md` says "keep the cap" and
Rev 1 had argued against it without ever citing it.

**Rev 3** audits that verdict document properly, and reaches the conclusion that Rev 2 was
too generous to it. The verdict is not a valid counter-argument. It is a stale, self-graded,
internally unfalsifiable document, and the repository contains its own falsifier, already
triggered. §2b is the audit.

**Rev 3 also corrects Rev 2's headline number.** Rev 2 said the pick universe is 24.
On the scheduler path it is **20**. Details in R4. I would rather hand you the correction
than have you find it.

**Rev 3.1 — citation audit, run at the user's request.** Every code quote, predicate and
table row below was re-fetched at `3a65d34a` and checked character by character. The
*content* of every citation held, but **every line number in Rev 3 was offset by +5**,
because my extractor prepends a five-line markdown header to each file before I grep it.
Do not trust Rev 3 line numbers; use the corrected anchors in §2a. Two substantive errors
and three over-claims were also found — see §2a and the corrected H8.

---

### §1 — The claims under review

**Claim A — infrastructure, provable from source.** The caps are a budget heuristic backed
by a stale self-assessment, not a safety requirement. The cost they were sized against is
mostly a Telegram scan the code itself documents as unable to change a score. Removing the
caps is the repository's *own recorded end state* (§2b H4), and its *own stated falsifier*
for that removal is already satisfied (§2b H5).

**Claim B — still contested, still yours.** Uncapped scoring fits inside the 480 s write
budget on 1 GB / 2 vCPU. Rev 1 asserted this. Rev 2 withdrew it. **Rev 3 restores it to
"arithmetically supported on the repo's own numbers, not measured end-to-end."** The
arithmetic is in F7 and the margin is not marginal — but `build_wall_seconds` at 127 names
has never been observed on prod, because observing it requires removing the cap. That
circularity is the one thing I cannot reason my way out of, and it is why F7 asks for a
sequenced trial rather than a flip.

---

### §2a — Citation audit (added Rev 3.1)

**Offset rule.** Rev 3's line numbers were produced by grepping an extracted copy that
carries a five-line markdown header. **Subtract 5 from every Rev 3 line number.** Corrected
anchors, re-verified at `3a65d34a` by direct file read:


| Item | Rev 3 said | Actual |
|---|---|---|
| `fly.toml` cap block | 94–98 | **89–93** |
| `fly.worker-v2.toml` cap block | 69–73 | **64–68** |
| `fly.worker-v2-essential-soak.toml` cap block | 80–84 | **75–79** |
| `server.py` `TOP_SCORING_UNIVERSE` | 652 | **647** |
| `server.py` `_cap_subnets_for_scoring` | 930–937 | **925–932** |
| `server.py` homepage shell / hourly pick | 1071 / 3368 | **1066 / 3363** |
| `scoring_cap.py` file length | 127 | **121** |
| `scoring_cap.py` `cap_subnets_for_scoring` | 96–127 | **91–121** |
| `pick_scheduler.py` `PICK_SCHEDULER_UNIVERSE_CAP` | 37 | **32** |
| `pick_scheduler.py` `_load_capped_subnets` | 156–163 | **151–161** |
| `pick_scheduler.py` `_tick` | 320–360 | **315–427** (`HourPickScheduler._tick` is 477–514) |
| `daily_pick_engine.py` `_subnets_for_pick_creation` | 210–217 | **205–212** |
| `pick_selection_audit.py` docstring claim | 11 | **6** |
| `pick_selection_audit.py` `POLICY_*` | 29–31 | **24–27** (29 is `ALL_POLICIES`) |
| `pick_selection_audit.py` `_scheduler_cap_limit` | 55–80 | **57–60** |
| `calibration.py` `calibration_for_subnet` | — | **238** |
| `calibration.py` row loop / netuid filter | — | **261–269** |
| `calibration.py` `applied` | — | **283** |
| `calibration.py` file length | 302 | **296** (295 newline characters; no trailing newline) |
| `state_vector.py` Telegram block | ~1897–1913 | **1893–1912** |
| `state_vector.py` contract key | — | **1960** |
| `rollup.py` `_conviction_rows` / `_query_conviction_rows` | 1082 | **1068 / 1077** |
| `rollup.py` first / second `LIMIT 3000` | 1096 / 1775 | **1096 / 1770** |
| `test_scoring_cap.py` / `test_pick_regen_universe_cap.py` | 87 / 64 | **86 / 63** |

**What held exactly.** Every quoted code block in R1–R12 and every verdict-doc quote in
§2b was re-fetched and matched character for character, including `return ranked[:cap]`,
`scores.get(netuid, -1.0)`, the four-conjunct `complete` predicate, the `_load_capped_subnets`
`min(24, TOP)`, the verdict header line, the `coverage_complete=1` gate, and the
`SCORE_SNAPSHOT_SCORE_WORKERS` and `TOP_SCORING_UNIVERSE (20)` rows. The ergo claims in
R1–R12 stand unchanged.

**Claims I over-claimed in Rev 3 — corrected or downgraded:**

1. **"No re-measure trigger in the verdict" — FALSE.** It contains "re-measure prod
   `build_wall_seconds`, RSS, `coverage_complete`, then trial **80 → 127**". H8 rewritten.
2. **"`bb4ce004` reached main with no PR and no audit" — inferred, not proven.** Verified
   only that its commit message carries no `(#NNNN)` merge reference while both neighbours
   do (`#1458`, `#1443`). A squash merge can omit the number. Treat as unverified.
3. **"No adversarial lane touched the verdict" — inferred.** What is verified: both commits
   are Cursor Agent, and the adversarial corrections doc
   (`mc-grok-corrections-2026-10-11.md`) is dated **Oct 11**, i.e. it predates the verdict by
   six days, so it cannot have reviewed it. That is not proof nobody read the verdict.

### §2 — Receipts

All fetched at `3a65d34a`. Line numbers re-derived from decoded content.

#### R1 — the cap is a fallback heuristic and its default is unreachable

`internal/subnets/scoring_cap.py`, 91–121 (of 121):

```python

def cap_subnets_for_scoring(
    subnets: List[Dict[str, Any]],
    limit: Optional[int] = None,
    *,
    default_limit: int = 40,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` subnets to score on hot paths / snapshot jobs."""
    cap = limit if limit is not None else default_limit
    if not subnets or len(subnets) <= cap:
        return list(subnets)

    try:
        from internal.council.score_snapshots import rank_subnets_by_snapshot

        ranked = rank_subnets_by_snapshot(subnets, horizon="day")
        if ranked:
            return ranked[:cap]
    except Exception:
        pass

    mega_ceiling = _env_int("SCORING_CAP_MEGA_CEILING_RANK", 10)
    mid_min = _env_int("SCORING_CAP_MID_RANK_MIN", 11)
    mid_max = _env_int("SCORING_CAP_MID_RANK_MAX", 75)

    pool = _heuristic_hunt_pool(
        subnets,
        mega_ceiling_rank=mega_ceiling,
        mid_min=mid_min,
        mid_max=mid_max,
    )
    return pool[:cap]
```

The "top 10 removed" framing is wrong: line 107 returns `ranked[:cap]`, a straight top-N
with **no** mega exclusion. `_heuristic_hunt_pool` and `SCORING_CAP_MEGA_CEILING_RANK` run
only when `rank_subnets_by_snapshot` raises or returns empty — the top-10 exclusion is the
*degraded path*. And `default_limit=40` is unreachable — but the reason given in Rev 3 was wrong.
The two callers that pass no `limit=` are `server.py:1214` (spotlight) and
`server.py:2946` (SimiVision); both go through `server._cap_subnets_for_scoring`, which
supplies `default_limit=TOP_SCORING_UNIVERSE` (`:647`, **20**). Every other caller
(`:1066`, `:3363`, `pick_scheduler.py:158`, `score_snapshots.py:674`,
`daily_pick_engine.py:212`, `pick_selection_audit.py:70`/`:72`) passes `limit=` explicitly.
So the literal default 40 is never reached — not because every caller passes `limit=`.

#### R2 — one env var, two readers, two answers

`internal/council/score_snapshots.py`, 38–60 and 667–676:

```python
SCORE_SNAPSHOT_MAX_SUBNETS = env_int("SCORE_SNAPSHOT_MAX_SUBNETS", 0)

def _snapshot_subnet_cap() -> int:
    """Cap scoring universe on small VMs; worker defaults to TOP_SCORING_UNIVERSE."""
    raw = os.environ.get("SCORE_SNAPSHOT_MAX_SUBNETS")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(0, int(raw))
        except ValueError:
            return 0
    try:
        from internal.run_mode import is_worker_mode

        if is_worker_mode():
            return int(os.environ.get("TOP_SCORING_UNIVERSE", "40"))
    except Exception:
        pass
    return 0

        cap = _snapshot_subnet_cap()
        capped_out = 0
        selection_policy = str(prep_meta.get("selection_basis") or "full")
        pre_cap_len = len(subnets or [])
        if cap > 0 and subnets and len(subnets) > cap:
            from server import _cap_subnets_for_scoring

            subnets = _cap_subnets_for_scoring(subnets, limit=cap)
            capped_out = max(0, pre_cap_len - len(subnets or []))
            selection_policy = "rank_cap"
```

The module constant reads the var with default `0`; `_snapshot_subnet_cap()` reads the same
var and then falls back to `TOP_SCORING_UNIVERSE`. Line 667 calls the **function**, so the
constant is dead weight unless Claude finds a reader (F1).

#### R3 — the cap is pinned in all three deploy configs

```
fly.toml:89                            SCORE_SNAPSHOT_MAX_SUBNETS = "40"
fly.toml:90                            SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS = "480"
fly.toml:91                            SCORING_CAP_MEGA_CEILING_RANK = "10"
fly.toml:92                            SCORING_CAP_MID_RANK_MIN = "11"
fly.toml:93                            SCORING_CAP_MID_RANK_MAX = "75"

fly.worker-v2.toml:64                  SCORE_SNAPSHOT_MAX_SUBNETS = "40"
fly.worker-v2.toml:65                  SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS = "480"
fly.worker-v2.toml:66                  SCORING_CAP_MEGA_CEILING_RANK = "10"
fly.worker-v2.toml:67                  SCORING_CAP_MID_RANK_MIN = "11"
fly.worker-v2.toml:68                  SCORING_CAP_MID_RANK_MAX = "75"


fly.worker-v2-essential-soak.toml:75   SCORE_SNAPSHOT_MAX_SUBNETS = "40"
fly.worker-v2-essential-soak.toml:76   SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS = "480"
fly.worker-v2-essential-soak.toml:77   SCORING_CAP_MEGA_CEILING_RANK = "10"
fly.worker-v2-essential-soak.toml:78   SCORING_CAP_MID_RANK_MIN = "11"
fly.worker-v2-essential-soak.toml:79   SCORING_CAP_MID_RANK_MAX = "75"
```

`TELEGRAM_EVIDENCE_CALIBRATION`, `TOP_SCORING_UNIVERSE` and `SCORE_SNAPSHOT_SCORE_WORKERS`
have **zero hits** in all three tomls.

**Note the shape of lines 89–93:** every neighbouring block in `fly.toml` carries an
explanatory comment ("# Web process: keep CPU for GET / + hydrate…", "# Issue #888:
hydrate cold price cache…"). The five cap lines carry **none**. Nothing in the deploy
config says why these exist, what they were sized against, or that they were provisional.
That absence is itself evidence in §2b H8.

#### R4 — the live universe is 20 on the scheduler, 24 on regen. Not 40. Not 24 everywhere.

This corrects Rev 2, which said 24 flatly. Four call sites, three different answers:

`server.py`, 647:

```python
TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))
```

`server.py`, 925–932:

```python
def _cap_subnets_for_scoring(
    subnets: List[Dict[str, Any]],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Limit council scoring — majors represented, mid-cap focus for the rest."""
    from internal.subnets.scoring_cap import cap_subnets_for_scoring

    return cap_subnets_for_scoring(subnets, limit, default_limit=TOP_SCORING_UNIVERSE)
```

`server.py`, 1066 (homepage shell) and 3363 (hourly pick):

```python
    return _cap_subnets_for_scoring(subnets, limit=min(24, TOP_SCORING_UNIVERSE))
...
            # Tight cap — full 40-universe select_hourly_pick is ~9s on Fly shared CPU.
            subnets = _cap_subnets_for_scoring(subnets, limit=min(24, TOP_SCORING_UNIVERSE))
```

`internal/council/pick_scheduler.py`, 32 and 151–161:

```python
PICK_SCHEDULER_UNIVERSE_CAP = int(os.environ.get("PICK_SCHEDULER_UNIVERSE_CAP", "24"))

def _load_capped_subnets() -> Any:
    """Lazy subnet snapshot capped for Fly safety (never full 127 here)."""
    try:
        from server import TOP_SCORING_UNIVERSE, _cap_subnets_for_scoring, _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
        cap = min(PICK_SCHEDULER_UNIVERSE_CAP, TOP_SCORING_UNIVERSE)
        return _cap_subnets_for_scoring(subnets or [], limit=cap)
```

`internal/council/daily_pick_engine.py`, 205–212:

```python
def _subnets_for_pick_creation(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same scoring universe as pick_scheduler — never select_daily_pick on full hydrate list."""
    from internal.subnets.scoring_cap import cap_subnets_for_scoring

    sched_cap = int(os.environ.get("PICK_SCHEDULER_UNIVERSE_CAP", "24"))
    top = int(os.environ.get("TOP_SCORING_UNIVERSE", "40"))
    limit = min(sched_cap, top)
    return cap_subnets_for_scoring(subnets, limit=limit)
```

Resolving, with `TOP_SCORING_UNIVERSE` unset everywhere (R3):

| Path | Reads | Value |
|---|---|---|
| `server.py` homepage shell, 1066 | `min(24, server.TOP)` = `min(24, 20)` | **20** |
| `server.py` hourly pick, 3363 | `min(24, server.TOP)` | **20** |
| `pick_scheduler._load_capped_subnets` | `min(24, server.TOP)` — imports from `server` | **20** |
| `daily_pick_engine._subnets_for_pick_creation` | `min(24, local default 40)` | **24** |
| `pick_selection_audit._scheduler_cap_limit` | `min(24, local default 40)` | **24** |

**The daily pick is selected from 20 subnets and can be regenerated from 24.**

Two consequences worth stopping on:

1. **The nightly audit replays the wrong universe.** `internal/council/pick_selection_audit.py`
   names its primary PASS gate `POLICY_SCHEDULER_24 = "scheduler_cap_24"` and documents it
   as "matches pick_scheduler universe" (line 6). It does not: the oracle replays 24, the
   scheduler scored 20. A netuid ranked 21–24 can therefore be reported as a
   `universe_mismatch` MISS that the real scheduler could never have produced. And
   `cursor-agents-communication/pick-audit-lock.md` builds the entire nightly selection
   oracle on that label ("**Primary PASS gate:** `scheduler_cap_24`"), with
   `full_universe` relegated to "Secondary replay (diagnostics only)".
2. **The pick can change universe between creation and regeneration** — 20 at first
   selection, 24 on the stale-candidate regen path.

This is already partially on the record: `cursor-agents-communication/audit-kit/findings/C9-TOP-SCORING-UNIVERSE-001.json`
marks `disposition: CONFIRMED` for the "server.py=20 vs council modules=40" collision, and
the cap-audit handoff states the correct arithmetic outright: "`PICK_SCHEDULER_UNIVERSE_CAP=24`
(upper bound — `pick_scheduler` uses `min(24, server.TOP)` → **20** on default web path,
not 24)". **Nobody propagated that correction to the verdict doc, to

`pick-audit-lock.md`, or to `pick_selection_audit.py`.**

#### R5 — the Telegram loop scans rows before it checks the netuid

`internal/message_intel/calibration.py`, `calibration_for_subnet`:

```python
    rows = conviction_rows if conviction_rows is not None else _conviction_rows(db)
    ...
    current = []
    for row in rows:
        proof = classify_call(row)
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if not proof["eligible"] or timestamp is None or timestamp < cutoff:
            continue
        if wanted not in _netuids_from_row(row):
            continue
        if proof["direction"] in {"up", "down"}:
            current.append((row, proof, timestamp))
```

`classify_call` and `_parse_ts` run on **every** row; the netuid filter is third.

#### R6 — the 3000-row claim is a code receipt

`internal/message_intel/rollup.py`, 1068 and 1077–1098:

```python
def _query_conviction_rows(db=None) -> List[Dict[str, Any]]:
    database = db or get_db()
    with database._connection() as conn:
        rows = conn.execute(
            """SELECT m.id, m.source, m.author_id, ... po.price_24h, po.price_24h_recorded_at
               FROM messages m
               LEFT JOIN message_analysis a ON a.message_id = m.id
               LEFT JOIN message_verdicts v ON v.message_id = m.id
               LEFT JOIN price_snapshots ps ON ps.message_id = m.id
               LEFT JOIN price_outcomes po ON po.message_id = m.id
               WHERE m.source = 'telegram'
               ORDER BY m.id DESC LIMIT 3000"""
```


Five-table join, filtered to `source='telegram'`, capped at 3000 rows. Called from
`calibration.py:194` and `calibration.py:247`. (A second `LIMIT 3000` at `rollup.py:1770`
is out of scope — do not touch it.)

#### R7 — the cost is paid unconditionally for an adjustment that is always zero

`internal/council/state_vector.py`, 1893–1912:

```python
    telegram_calibration = None
    try:
        # Lazy, read-only boundary: Telegram history never changes council weights
        # and is default-off until operators explicitly enable it.
        from internal.message_intel.calibration import calibration_for_subnet

        conviction_rows = (market_context or {}).get("telegram_conviction_rows")
        telegram_calibration = calibration_for_subnet(
            sn.get("netuid") or sn.get("id"),
            conviction_rows=conviction_rows,
            calibration_health_snapshot=(market_context or {}).get(
                "telegram_calibration_health"
            ),
        )
        total = min(100.0, max(0.0, round(total + telegram_calibration["adjustment_points"], 2)))
```

No enable-check on the call. Inside `calibration_for_subnet`, `applied` requires
`health["active"]`, which is gated on `_flag("TELEGRAM_EVIDENCE_CALIBRATION")` (default
`False`, set in no toml). So `points` stays `0.0` and the `total` rebind is a no-op —
after burning R5 and R6.

#### R8 — the hoist fixed the query, not the loop

`internal/council/scoring_context.py`:


```python
def enrich_scoring_market_context(
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hoist Telegram conviction rows + health once per scoring batch.

    Without this, ``calibration_for_subnet`` loads up to 3000 SQLite rows per
    subnet via ``_conviction_rows()`` (Ditto: ~800ms/name on prod-shaped paths).
    """
```

Accurate about the SQLite read. Silent about the per-row classification loop.

#### R9 — `coverage_complete` is structurally unsatisfiable while a cap binds

**This is the finding that decides the verdict argument.** See §2b H3 for why it matters;
here is the mechanism.

`internal/council/snapshot_coverage.py`, line 1:

```python
"""Phase 1 score-snapshot coverage telemetry (honesty only — no cap policy change)."""
```

The authors wrote down that they were reporting honestly and deliberately **not** changing
cap policy.

`snapshot_coverage.py`, 203–208 — the denominator:

```python
def scoring_expected_netuids(
    membership_netuids: List[int],
    tradable_rows: List[Dict[str, Any]],
) -> List[int]:
    """Backward-compatible alias — denominator is full membership only."""
    return membership_scoring_expected(membership_netuids)
```

`snapshot_coverage.py`, 354–359 — the completeness predicate:

```python
    horizons_complete = day_block["complete"] and hour_ok
    complete = bool(
        published
        and membership_ok
        and horizons_complete
        and capped_out == 0
    )
```

And `capped_out` is exactly what `score_snapshots.py` sets to `pre_cap_len - len(subnets)`
whenever the cap truncates (R2).

**Therefore: `coverage_complete == 1` requires `capped_out == 0`, which requires that
nothing was capped.** While `SCORE_SNAPSHOT_MAX_SUBNETS=40` and membership exceeds 40,
`coverage_complete` is pinned at false. The measurement log already recorded it on live
prod:

```
| `subnet_score_snapshot_coverage_complete` | **0.0** | Last cycle not "complete" vs full membership |
```

Two further consequences:

- `note_cycle()` increments `_consecutive_partial_cycles` on every non-complete cycle. With
  the cap binding, **every cycle is partial, forever.** A real coverage regression and the
  standing cap are indistinguishable in that counter — the alerting channel is poisoned at
  the source.
- Any consumer that gates on `coverage_complete` is gated shut permanently. Enumerate them
  before deleting the cap (F9).

#### R10 — the rank input starves exactly what the desk is built to find

`internal/council/score_snapshots.py`, `rank_subnets_by_snapshot`, 237–270:

```python
def rank_subnets_by_snapshot(...) -> Optional[List[Dict[str, Any]]]:
    """Return subnets sorted by snapshot score, or None if snapshot missing/stale."""
    age = snapshot_age_seconds(path)
    limit = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    if age is None or age > limit:
        return None
    ...
    scores: Dict[int, float] = {}
    for row in snap.get(horizon) or snap.get("day") or []:
        ...
        return (scores.get(netuid, -1.0), float(s.get("emission") or 0))
```

A netuid absent from the snapshot keys to `-1.0` — below any scored name. Since
`cap_subnets_for_scoring` slices `ranked[:cap]` (R1), an absent netuid sorts last and is
cut. Absent *because* it was cut last cycle. **The cap is self-sealing: capped-out →
not in snapshot → −1.0 → ranked last → capped out again.**

That is the opposite of the desk's purpose. The system exists to surface BUILDING and
JUST STARTED subnets (see the pump-desk product description: ~129–200 subnets monitored,
with BUILDING/JUST STARTED as the priority tier). A brand-new netuid has no snapshot
history and can only enter through the 24- or 20-slot door if it already has a score.
Until it gets one, it cannot. Removal breaks the loop; the alternative fix is a rank
sentinel that does not sort last (e.g. neutral, or excluded from `[:cap]` ordering).

#### R11 — `is_worker_mode` definition

`internal/run_mode.py`:

```python
def get_run_mode() -> str:
    return os.environ.get("RUN_MODE", "web").strip().lower()

def is_worker_mode() -> bool:
    return get_run_mode() == "worker"
```

On the v1 topology (`fly.toml` sets `RUN_MODE = "web"`) the snapshot job runs under web

mode, where `_snapshot_subnet_cap()` would return 0 — except `SCORE_SNAPSHOT_MAX_SUBNETS=40`
short-circuits first at lines 47–50. The cap is applied by env, not by mode.

#### R12 — `telegram_evidence_calibration` is a persisted contract

`internal/council/daily_pick.py`:


```python
        "active_signals": learning["active_signals"],
        "telegram_evidence_calibration": score_payload.get("telegram_evidence_calibration"),
```

`internal/council/pick_explain.py`:

```python
    if verdict == "published" and isinstance(today.get("pick"), dict):
        persisted_cal = today["pick"].get("telegram_evidence_calibration")
```

`tests/test_pick_explain.py`:

```python
        f"telegram_evidence_calibration was mutated during enrichment; "
        f"expected {_SENTINEL_CAL!r}, got {pick_obj['telegram_evidence_calibration']!r}"

def test_pick_explain_calibration_field_contract():
    """telegram_evidence_calibration must appear at the top level of a successful
```

Written into persisted picks, read back by pick-explain, pinned by a contract test.
Cannot be a delete — see F4.

---

### §2b — The verdict document, audited

`docs/agent-friendly/scoring-caps-verdict.md`. This section exists because Rev 2 deferred
to it and that deference was wrong. Ten holes, in order of how much weight they carry.

#### H1 — It was written by the agent whose work it grades, in the same commit, seven minutes apart

Commit history for the path:

```
61d49f3fcc  2026-10-17T21:53:01Z  Cursor Agent
  feat(scoring): read top-picks and weighed shortlist from score snapshot
  ... Adds tests and agent-friendly measurement/verdict notes.

49faea952f  2026-10-17T22:09:17Z  Cursor Agent
  feat(scoring): profile-driven hoist, parallel snapshot scoring, snapshot API reads
  - Hoist telegram conviction rows, calibration health, scenario memory per batch
  - Bounded parallel day scoring (SCORE_SNAPSHOT_SCORE_WORKERS=4)
  - Profile docs: prod vs local gap, hoist quantification, dead-work audit
```

The verdict was authored by the same agent, in the same series, sixteen minutes after
writing the measurement and profile docs it reasons from, and in the same commit that
shipped two of the optimizations being graded. No adversarial lane touched it. Compare
`mc-grok-corrections-2026-10-11.md`, which exists precisely because a second agent
attacked the first one's cap reasoning and **modified** it. The verdict contains no such
record.

#### H2 — Its central number predates the fix it was written alongside, and the doc says so

The verdict's own table header:

```markdown
**Prod commit (deploy):** ``ef234c95`` · **Hoist on prod:** **No** · **Draft fixes:** ``cursor/scoring-profile-2b73``
```

And its sibling, `scoring-caps-profile.md`:

```markdown
| Mechanism | On `ef234c95` prod? | Evidence |
| Telegram `_conviction_rows` + `calibration_health` **once per batch** | **No** | ... |
| `calibration_health_snapshot` reuse | **No** | ... |
| Scenario `get_scenarios(300)` once per batch | **No** | ... |
```

So: the "Keep the cap — build 57.7 s/40" row is a measurement of a build **without the
hoist**, taken at 20:28Z deploy. The hoist landed on main at 22:09Z — the same commit that
finalised the verdict. **The verdict's load-bearing number was never re-measured after the
optimization it was written next to.** A doc that says "Keep until prod proves full N" while
declaring at the top that the thing that changes N's cost is not yet deployed is not a
verdict; it is a snapshot of a precondition.

#### H3 — Its gate cannot be satisfied. "Keep until prod proves full N" is a closed loop.

The verdict's gate:

```markdown
## Read-only prod proof for raising cap=40

`GET /metrics`: `coverage_complete=1`, `build_wall_seconds < 480×(40/N)`, RSS < 900MB,
stable `rate_limited` counter during cycle.
```

And §2 R9: `complete` requires `capped_out == 0`, with the denominator set to **full
membership**.

```
coverage_complete == 1  ⟹  capped_out == 0  ⟹  nothing was capped
                                               ⟹  the cap is already gone
```

**The stated precondition for removing the cap is only reachable after the cap is
removed.** That is not a conservative gate; it is an unfalsifiable one, and it converts
"keep" into a permanent default that no evidence can overturn. The measurement log's own
`coverage_complete = 0.0` is the system reporting its own permanent unfitness.

This hole alone is sufficient to reject the verdict as authority. Claude should feel free
to confirm it independently rather than trust my parse — the predicate is four conjuncts on
one `bool()` and the sentinel is one dict lookup.

#### H4 — It contradicts the prior audit's recorded end state

`cursor-agents-communication/audit-kit/cap-audit/mc-grok-corrections-2026-10-11.md`, §3:

```markdown
- **Authority is a membership resolver, not a magic integer. Do not replace 40 with
  128/129/64 as policy.**
- Split `TOP_SCORING_UNIVERSE` into **scoring set** (background = membership, **no count
  cap at end state**), **request-path latency budget**, **pick candidate pool**
  (snapshot-fed top-K).
```

The end state on record is **no count cap**. The verdict's "Keep" rows are interim
positions that never cite this, never say they are interim, and never say what supersedes
them. Anyone reading the verdict alone would conclude the caps are settled policy. Anyone
reading the earlier audit would conclude they are a waypoint. Both documents are on main.

#### H5 — Its own falsifier is already triggered

Same file, §2, the taxonomy table and the falsifier block:

```markdown
| Snapshot **count** cap on background (`SCORE_SNAPSHOT_MAX_SUBNETS` when it truncates
  membership) | **A after Phase 1 RSS**, still **B** until coverage exists | Safety role
  today is VM budget; uncap only after measured snapshot job |

**Falsifier for D→A order:** production already emits `complete`/`capped_out` and never
`ok` on skip — then A on snapshot cap can start without a telemetry phase.
```

Production **does** emit `complete` and `capped_out`: `snapshot_coverage.build_coverage_block`
returns both keys, `score_snapshots.py` populates `capped_out`, and the measurement log
quotes `coverage_complete 0.0` from the live `/metrics` feed. The named falsifier is
satisfied. By the prior audit's own rule, **A (removal) can start.**


The second falsifier — "for moving scheduler cap to A: pick tick already snapshot-only with
no `score_universe` on the 90s path" — is **not** satisfied, and I want that stated plainly
because it is the one place the verdict wins. `pick_scheduler._tick` (315–427) calls
`_load_capped_subnets()` → `get_or_create_today_pick(subnets, ctx, ...)` inside a
`ThreadPoolExecutor` with `DAILY_PICK_TICK_TIMEOUT_SECONDS`. It never calls `score_universe`
by name, but it scores synchronously through the pick engine. **The scheduler cap is a real
latency budget. Remove it second, not first.** This is F8's whole content.

#### H6 — It treats a measure the sibling doc explicitly falsified as valid when convenient

Verdict, row `SCORE_SNAPSHOT_SCORE_WORKERS`: "**Ship** default 4 | Local 128-name wall
0.068→0.061 s (thin); prod win TBD".

Measurement doc, on the same class of number:

```markdown
**Falsifier attempted:** Local `REGISTRY_ONLY` bench scored 129 subnets in **0.12 s** —
**not prod representative** (no pump ladder, calibration rebuild, or live OHLCV). Reject as
evidence against 170 s.
```

Local sandbox walls are rejected as evidence when they undercut the "keep" story, and
accepted when they support the "ship 4" row. It is marked "(thin)" and "prod win TBD", so
the doc half-knows. But it still resolves to **Ship**, and a later reader sees a shipped
verdict, not a thin one. On a 2 vCPU machine, 4 workers is 2× oversubscription concluded
from a sandbox. That is F6's job, not a settled row.

#### H7 — One row is a defect mislabelled as a decision

Verdict row: "`TOP_SCORING_UNIVERSE` (**20**) web | **Replace** with snapshot reads
(draft)". There is no considered "20 on web". There are four defaults for one symbol
(`server` 20 / `daily_pick_engine` 40 / `score_snapshots` 40 / `pick_selection_audit` 40),
already recorded as `C9-TOP-SCORING-UNIVERSE-001` with `disposition: CONFIRMED` at pin
`ce3d820`, and the `min(24, TOP)` consequence is **20 vs 24 by path** (R4). A collision
was written down as a policy.

#### H8 — No owner, no expiry, no decision rule — and Rev 3 was wrong that it has no trial plan

**Rev 3 overstated this hole. Rev 3.1 corrects it.** Re-reading the doc in full, the verdict
*does* contain a re-measure trigger and a staged trial:

```markdown
After draft lands: re-measure prod `build_wall_seconds`, RSS, `coverage_complete`, then
trial **80 → 127** cap with read-only metrics gate above.
```

Rev 3's claim of "no re-measure trigger" was false. What the verdict still lacks: an
**owner**, an **expiry date**, and a **decision rule** for when the trial is never run or
the gate is never met — which, per H3, is the guaranteed case. An 80 → 127 trial gated on
`coverage_complete=1` cannot start. So the plan exists and is unreachable, which is worse
than no plan: it reads as scheduled diligence while being inert.

The config agrees on the provenance gap: the five cap lines in `fly.toml` (89–93) are the
only lines in that contiguous block with no comment at all (R3, anchor-corrected). Nothing
records the caps as bounded in time.

#### H9 — It sizes a safety control against work the code calls inert


The cap exists to bound `build_wall_seconds`. Per the profile doc, 55.8–69.3% of that wall
is the Telegram scan (F7 arithmetic) — and per R7 that scan feeds an adjustment that is
structurally `0.0`. **The control was calibrated against mostly dead work.** Its trigger
threshold is real; its justification is inflated by the exact component we are deleting.
Once the dead work is gone the same cap protects against a much smaller number, which is
why F7's gate passes (F7 table).

#### H10 — It never touches the starvation defect underneath

Neither the verdict nor the measurement log mentions `scores.get(netuid, -1.0)` (R10). The
cap's rank input systematically demotes subnets with no snapshot history — new and BUILDING
netuids, which are the product's target. A "keep" recommendation that does not address a
self-sealing rank sentinel under it is incomplete on its own terms.

#### What survives the audit

To be fair to it, because Claude will check:

- **`build_wall_seconds = 57.70 s is a background build, not an HTTP handler.** The
  measurement doc says so explicitly. Rev 1 conflated these; that was wrong and this is now
  the anchor for F7.
- **`coverage_complete=0.0` and "40 of 40 day scores, hour copied from day"** are real
  measured values and they constrain the work correctly.
- **RSS ~413 MB at 40 names** is real and is the number that matters for 1 GB.
- **"Do not raise 480 s"** (prior audit) and the 480 pin are consistent and correct.
- **And one row I missed in Rev 3, which is the strongest single support in the doc:**
  the verdict's *own* handler row computes `~0.65 s/name × 127 ≈ 83 s background`. That is
  its own **post-hoist** figure, and it lands within 3% of §F7's post-Telegram-removal
  estimate (0.6375 s/name → 81 s). Two independent routes converge, and **no sustained
  build can approach the 480 s budget at either**. The verdict reached the number that
  licenses the trial and then kept the cap anyway. That is the contradiction in one row.
- **The 40→N extrapolation arithmetic is sound** — the error was in what it was applied to,
  not in the division.

---

### §3 — Scope, exhaustive

Derived from symbol search for `cap_subnets_for_scoring`, `PICK_SCHEDULER_UNIVERSE_CAP`,
`TOP_SCORING_UNIVERSE` at `3a65d34a`, plus direct reads.

**Delete outright**
- `internal/subnets/scoring_cap.py` (121 lines)
- `internal/message_intel/calibration.py` (296 lines)
- `tests/test_telegram_evidence_calibration.py`
- `tests/test_scoring_cap.py` (86 lines — imports `cap_subnets_for_scoring`, autouse
  fixture stubs `rank_subnets_by_snapshot`)
- `tests/test_pick_regen_universe_cap.py` (63 lines — note it sets
  `TOP_SCORING_UNIVERSE=40` in the monkeypatch, which masks R4's default-20 path; deleting
  it is correct and it was never testing what it claimed)

**Edit — snapshot path (first)**
- `internal/council/score_snapshots.py`: `_snapshot_subnet_cap()` (45–60), the `cap > 0`
  block (667–676), `capped_out` / `selection_policy = "rank_cap"` (676, 739–740)
- `server.py`: `_cap_subnets_for_scoring` (925–932), `TOP_SCORING_UNIVERSE` (647)

**Edit — pick path (second, sequenced — F8)**
- `internal/council/pick_scheduler.py`: `PICK_SCHEDULER_UNIVERSE_CAP` (32),
  `_load_capped_subnets` (151–161)
- `internal/council/daily_pick_engine.py`: `_subnets_for_pick_creation` (205–212)
- `internal/council/pick_selection_audit.py`: `_scheduler_cap_limit` (57–60),
  `universe_for_policy` (63–75), `POLICY_*` constants (24–27; 29 is `ALL_POLICIES`), the
  "matches pick_scheduler universe" claim (6), the `cap-24` literal (232), and the
  `cap-{_scheduler_cap_limit()}` f-string (237).
  **This file's oracle is wrong today (R4); fixing the universe is not optional.**
- `cursor-agents-communication/pick-audit-lock.md`: `scheduler_cap_24` is mislabelled —
  either fix the label or record that 20 is the live value
- `tests/test_pick_selection_audit.py`: drop cap expectations

**Edit — Telegram out of scoring**
- `internal/council/state_vector.py`: R7 block + `telegram_evidence_calibration` key
- `internal/council/scoring_context.py`: drop `telegram_conviction_rows` /
  `telegram_calibration_health`; add `scenario_memory_by_netuid`
- `internal/council/memory_scoring.py`: consume the index (F5)
- `internal/message_intel/engine.py`: `telegram_calibration_status`
- `internal/message_intel/routes.py`: `api_message_intel_calibration`
- `internal/council/daily_pick.py`, `internal/council/pick_explain.py`,
  `tests/test_pick_explain.py`: R12 / F4
- `tests/test_score_snapshots.py`: references both cap symbols at `:98–100`
  (`_cap_subnets_for_scoring(rows, limit=5)`) and `:258–262`
  (`test_snapshot_subnet_cap_defaults_on_worker`) — **do not delete this file**;
  surgical edits only. The second one also pins the `TOP_SCORING_UNIVERSE` worker
  fallback that R2 relies on.

- `tests/test_ohlcv_call_quality.py` (`:23–24`) and `tests/test_market_feed_quality.py`
  (`:59–60`): **both are assertions, not setup.** Neither file exercises the cap for any
  other purpose — drop those two tests and keep the `_safe_simivision_payload` tests
  that share the file.

**Docs — three files, not one**
- `docs/agent-friendly/scoring-caps-verdict.md`: its "Keep" rows and its
  `coverage_complete=1` gate are superseded. **Rewrite, do not delete** — replace the
  unsatisfiable gate with the F7 measurement plan and mark the H3 circularity explicitly so
  the next audit cannot re-litigate from it.
- `docs/agent-friendly/scoring-caps-measurement.md`: keep as historical measurement; add a
  dated note that the pin is `ef234c95` pre-hoist and the coverage value was
  cap-induced, not degradation-induced.

- `docs/agent-friendly/scoring-caps-profile.md`: same dated note. Its "Hoist on prod? No"
  table is true of `ef234c95` and false of base.

**Keep, deliberately**
- `internal/message_intel/rollup.py` — ingestion stays a feature; it stops feeding a score.
  Second `LIMIT 3000` (1770) out of scope.
- `JUDGES_SCORING_UNIVERSE` — hydration guard, not a scoring cap. Out of scope; say so.
- Score weighting (`weighted + value_boost + flow_boost + size_tilt`) — model, not filter.
- `rank_subnets_by_snapshot` as a *display/pick ranking* — but the `-1.0` sentinel (R10)
  is a defect and must be fixed or the starvation persists after the cap goes.

**Config — 3 tomls**
- Delete `SCORE_SNAPSHOT_MAX_SUBNETS`, `SCORING_CAP_MEGA_CEILING_RANK`,
  `SCORING_CAP_MID_RANK_MIN`, `SCORING_CAP_MID_RANK_MAX`, `PICK_SCHEDULER_UNIVERSE_CAP`
  (not present in the tomls — code defaults only).
- `SCORE_SNAPSHOT_SCORE_WORKERS`: do not pin 2 by fiat (F6).

---

### §4 — What I want attacked

**F1.** Prove the R2 constant dead or live. Enumerate readers of `SCORE_SNAPSHOT_MAX_SUBNETS`.

**F2.** Invariant: N in → N out for N ∈ {1, 24, 40, 127, 200}, on both the snapshot path and
the `_load_capped_subnets` → `get_or_create_today_pick` path. I expect it to break on the
pick path via R4.

**F3.** R7 claims the adjustment is structurally zero. Enumerate every route by which
`health["active"]` becomes true; check whether `TELEGRAM_EVIDENCE_CALIBRATION` can be set
outside the repo (`fly secrets`, Procfile, workflow env). If it can, "always zero" is
conditional.

**F4.** R12 compat decision. Options: (a) keep the key, always `None`, mark deprecated;
(b) migrate persisted picks, tolerate absence; (c) keep a minimal struct, delete only the
scan. Recommend one, name the risk, state what the contract test becomes. **(a) is my
default.**

**F5.** Is `scenario_outcome_adjustment` (`memory_scoring.py`, ±2 pt cap) inside the
"no filter" guarantee or a fourth heuristic? I treat it as a score adjustment to be
indexed, not a universe filter to be deleted. Refute if wrong.

**F6.** `SCORE_SNAPSHOT_SCORE_WORKERS`: 4 vs 2 vCPU. Settle with prod evidence or leave the
default and say so. Do not pin 2 because I suggested it in Rev 1; do not keep 4 because
the verdict says "Ship" on a sandbox number (H6).

**F7 — the load-bearing one: does uncapped fit 480 s?** Using the repo's own numbers only.

Measured at `ef234c95` (pre-hoist), 40 names, background build:

```
per-name prod cost      57.70 / 40              = 1.4425 s
Telegram share @805ms   40 × 0.805 / 57.70      = 55.8%
Telegram share @1.0s    40 × 1.000 / 57.70      = 69.3%
per-name after removal  25.50 / 40  (@805ms)    = 0.6375 s/name
                        17.70 / 40  (@1.0s)     = 0.4425 s/name
127 names, post-removal 0.6375 × 127            = 81.0 s
                        0.4425 × 127            = 56.2 s
Verdict's own gate      480 × (40/127)          = 151.2 s
127 names, naive        1.4425 × 127            = 183.2 s   ← what the verdict extrapolated
```

So the verdict's 183 s comes from applying pre-hoist per-name cost to an uncapped universe
**without removing Telegram**. Remove the component the packet exists to remove and the same
arithmetic lands at **56–81 s against a 151 s gate** — a 1.9× to 2.7× margin. Parallel
workers (`SCORE_SNAPSHOT_SCORE_WORKERS`) would improve it further on CPU-bound portions;
I claim no number for that.

Settle these three, in this order:
1. Confirm `57.70 s` is a **background build wall**, not a request-path number — the
   measurement doc says so and it changes what a budget means.
2. Confirm or refute the Telegram-share subtraction. If the hoist already removed most of it
   at base (it is deployed in code at `3a65d34a`), the per-name figure is **lower** than my
   post-removal estimate, not higher — `_conviction_rows` is hoisted once per batch today.
   Then what remains per name is `classify_call` over up to 3000 rows (R5). **That is the
   open measurement**: how long does one `classify_call` loop take, × 127, against 151 s?
3. State the measurement plan for the 127-name wall, given it cannot be observed without
   removing the cap: a staged trial (40 → 80 → 127) with `build_wall_seconds`, RSS,
   `capped_out`, `coverage_complete`, and `rate_limited` read at each step, on the soak
   config first.

**My position, stated so it can be shot down:** no silent truncation. Either the full
universe, or a recorded budget shortfall that sets `coverage_complete=false` **because of
the budget**, not because of a cap constant. A cap that increments `capped_out` and
continues is the worst of both: it makes the honest metric permanently unhealthy (R9) and
hides which of the two causes is real.

**F8 — sequencing, and this one is a hard constraint.** The snapshot cap and the scheduler
cap are not the same control and must not ship together:

- **Snapshot cap → remove first.** Background path, no request latency. The prior audit's
  falsifier for A is satisfied (H5).
- **Scheduler cap → remove second.** `pick_scheduler._tick` still scores synchronously
  inside `get_or_create_today_pick` under `DAILY_PICK_TICK_TIMEOUT_SECONDS` (H5, R4).
  Removing it first reintroduces sync scoring on the 90 s tick. Refute only if you can show
  the tick is snapshot-fed at base — it is not, per `pick_scheduler.py:319–336` and the
  absence of any `score_universe` call. It applies a cap twice, in fact:
  `_load_capped_subnets()` (defined `:151`, called `:321`; `min(24, TOP_SCORING_UNIVERSE)`, which is 20 at the `server.py` default and 24 at the deployed 40) and then `daily_pick_engine.py:343`
  (`_subnets_for_pick_creation`, min(24, 40) = 24) — the second cannot widen the first.

**F9 — consumers of `coverage_complete`.** Enumerate every reader. With `capped_out == 0`
in the predicate, `complete` has been false since the cap was set. Find out what has been
gating on a permanently-false flag, and whether anything has been silently suppressed by it.
This is a bigger question than the cap and may deserve its own packet.

**F10 — what does the daily pick do with 20 vs 24?** With `pick_selection_audit` replaying 24
against a scheduler that used 20, has any recorded audit PASS/MISS been computed against the
wrong universe? Check `data/pick_audits/` history if present. If audits exist, their MISS
classifications may be unreliable — that is a finding about the audit, not just the cap.

---


### §5 — Invariants to land as tests

1. N in → N out at N ∈ {1, 24, 40, 127, 200}; no row dropped, no silent slice.
2. `coverage_complete` is computed against full membership and **is satisfiable**: a run with
   the full universe yields `capped_out == 0` and `complete == True`. A test that asserts
   `complete is False` while a cap binds is the H3 bug written down.
3. Telegram removal changes no score: assert the pre-removal adjustment is `0.0` on the
   sample set, then assert equality.
4. Grep guard: no module imports `scoring_cap`, `TOP_SCORING_UNIVERSE`,
   `PICK_SCHEDULER_UNIVERSE_CAP`.
5. `SCORE_SNAPSHOT_MAX_SUBNETS` has exactly one reader, or zero.
6. `TOP_SCORING_UNIVERSE` has exactly one default. A CI check for duplicate defaults across
   modules — `C9-TOP-SCORING-UNIVERSE-001` regressed once and should not again.
7. Regression for R4: assert the pick universe the audit replays equals the one the
   scheduler used. Today that test fails at 24 vs 20; written before the fix it is the
   receipt.
8. Regression for R10: a netuid with no snapshot row must not sort below scored netuids in
   a way that guarantees starvation — either it is ranked neutrally or the cap is gone.
9. `consecutive_partial_cycles` must be able to return to 0 in a healthy system.

---

### §6 — GAPS (unverified, stated as unverified)

1. **`~800ms/name` and the 805 ms `_conviction_rows` figure.** Two in-repo sources
   (R8 docstring, profile doc). **Not measured by me.** Treated as the repo's number.
2. **The 57.70 s / 1.44 s-per-name / RSS 413 MB figures.** Quoted verbatim from
   `scoring-caps-measurement.md`, dated at prod commit `ef234c95` — **pre-hoist, not
   re-measured at `3a65d34a`.**
3. **`TELEGRAM_EVIDENCE_CALIBRATION` unset in deploy.** Proven for repo files only. Could be
   set through `fly secrets`, invisible to the repo. Unverified against live config.
4. **`pick_selection_audit.py` behaviour unread beyond lines 6, 24–29, 57–75, 232, 237 and 249 (cap assignments 57–60; docstring claim line 6).**
   The rest of the file is unread; F10 depends on it.
5. **Whether `data/pick_audits/` history exists and covers the 20-vs-24 window.** Not
   checked.
6. **`classify_call` unit cost.** The single number that decides F7 after the hoist. Never
   measured, by me or apparently by anyone. **Rev 3.1:** HEAD (`3a65d34a`, merged `#1458`)
   added `internal/build_cost.py` with `conviction_queries` / `conviction_query_seconds`
   counters. That is good and it **does not close this gap**: it times the SQLite read
   (`_conviction_rows`), which the hoist already reduced to ~1 per build. The remaining

   per-name cost is the `classify_call` + `_parse_ts` loop over up to 3000 rows
   (`calibration.py` 261–269), which `build_cost` does not instrument. If F7 is to be
   settled by measurement rather than arithmetic, that loop needs its own counter — or the
   loop gets deleted first, which satisfies F7 trivially.

Rev 2's GAPS 1, 5 and 6 remain closed. Rev 3 adds 4, 5, 6.

---

### §7 — Fence

No push to `main`. No merge. No `fly-deploy` label. No deploy.

Tier 3 additionally: **explicit operator go/no-go before any PR is opened.** This touches
the core scoring loop, writes snapshots, edits three deploy configs, and changes the
universe the daily pick is selected from and audited against.

Two standing notes, restated rather than inherited:
- `bb4ce004` reached `main` on `2026-10-18` with no PR and no audit. That is the precedent
  this fence exists to prevent.
- `scoring-caps-verdict.md` is **not** authority. It is a pre-hoist snapshot, self-graded,
  with an unsatisfiable gate. It is cited here so its measurements get used and its stale
  rows get corrected — not so it can settle anything.

---

## Part III — Tier 2 read cost: instrumentation audit and proposed fixes

Pin: `3a65d34ac46a28395559310f21db013b4581c645` (cryptoreporthub/subnet-dashboard)
Status: read-only. Nothing pushed, nothing written to the repo.

---

### 1. Corrections to my previous message

I asserted three things the code does not support. Recording them because they change the conclusion.

**Wrong: "~1% of overhead" is a measurement.** It was never a measurement, and it is not recoverable from `build_cost`. That part holds. What follows is me then over-claiming in the fix direction.

**Wrong: "`guarded_load` returns `_meta` and every caller throws it away."**
`engine.py:328` captures it, and `engine.py:360-362` consumes it:

```python
    if cache_meta.get("stale"):
        meta["stale"] = True
        meta["cache_source"] = cache_meta.get("cache")
```

So cache state reaches clients — but only on the stale branch, as a client-facing flag. Not telemetry, and hits/refreshes stay invisible. The distinction matters: the plumbing is live, not dead.

**Wrong: "one edit covers `_proof_rows`, `panel_summaries`, `mindmap`, `cockpit`."**
`load_guard` covers six call sites, all inside `message_intel`. `panel_summaries`, `mindmap` and `cockpit` do not pass through it — they carry their own outer TTL caches. The guard seam instruments Tier 2's data layer, not the panels.

---

### 2. Verified instrumentation map

`build_cost` (`internal/build_cost.py`)

| Line | Fact |
|---|---|
| `:35-44` | `record()` handles `conviction` and `rpc` only; no `else` — unknown kinds vanish |
| `:21-30` | One process-wide `_active` dict, opened by `begin()` |
| `:49-50` in `end()` | no active window → returns `{}` |

Producers of the two kinds:

| File:line | Call |
|---|---|
| `internal/council/score_snapshots.py:707` | `build_cost.begin(...)` |
| `internal/council/score_snapshots.py:709` | `build_full_universe_snapshot(...)` — the only window |
| `internal/council/score_snapshots.py:715` | `build_cost.end()` |
| `internal/council/score_snapshots.py:725` | `timing["build_cost"] = cost` |
| `internal/chain_client.py:306` | `record("rpc", ...)` |
| `internal/message_intel/rollup.py:1074` | `record("conviction", ...)` inside `_conviction_rows` |

`tests/test_build_cost.py:21-35` asserts exactly those two counters and nothing else — the limitation is encoded as intended behaviour.

**Consequence:** the window is the snapshot build, and the only message-intel path counted is `_conviction_rows` (Tier 1 scoring). Tier 2 reads happen outside the window, or on a kind that is dropped.

`load_guard` call sites — the actual Tier 2 seam (label = `key[0]`)

| Key | Site | TTL |
|---|---|---|
| `message_rows` | `rollup.py:236` | 30s |
| `trending_subnets` | `rollup.py:300` | 30s |
| `proof_rows` | `rollup.py:1062` | 30s |
| `db.list_messages` | `models.py:328` | 30s |
| `db.netuid_sentiment_rollup` | `models.py:668` | 30s |
| `engine.list_messages` | `engine.py:328` | 30s |

`guarded_load` (`load_guard.py:181-249`) already classifies every outcome it returns — `hit`, `stale_immediate`, `stale_timeout`, `stale_partial_timeout`, `partial_timeout_uncached`, `refresh` — and then discards the timing. `guarded_list_load` (`:259`) drops `_meta` entirely. The sixth outcome, `LoadTimeout`, is raised at `:224` and never classified at all.

---

### 3. The hot path nobody measured

`/api/message-intel/status` is described in-code as *"the most-polled status surface on the homepage hydrate path"* (`routes.py:194-197`). It calls `_status_payload()` → `live_stats()` (`routes.py:169`) on **every poll**, uncached.

`store.py:66-87` — per call:

```sql
SELECT COUNT(*) FROM messages
SELECT source, COUNT(*) FROM messages GROUP BY source ORDER BY n DESC
SELECT COUNT(*) FROM message_verdicts WHERE conviction >= 60
SELECT ... FROM messages m LEFT JOIN message_verdicts v ... ORDER BY m.id DESC LIMIT 5
SELECT timestamp FROM messages ORDER BY id DESC LIMIT 1
```

Three are full-table aggregates. None is guarded, cached, or appears in `build_cost` or any Prometheus metric. `listener_status()` then hits SQLite twice more, per the comment at `routes.py:194`.

Other uncached call sites:

- `engine.py:402` — `meta = live_stats(db)` at the top of `_list_messages_impl`: once per cache refresh per distinct key.
- `summary.py:20` inside `summarize_message_intel()`, then `sections.py:368` calls `live_stats()` again — a cockpit build pays it twice.
- `routes.py:169` — the status poll above.

The honest claim is therefore: **the most-polled endpoint on the homepage hydrate path runs three full-table aggregates per poll, uncached and uninstrumented.** Far more specific than "Tier 2 is ~1%," and it is what should be measured first.

---

### 4. Side finding: comment/code drift in the filtered list path

`engine.py:396-400`:

```python
    # ponytail: filtered queries scan recent 200 rows max — enough for desk feed, not full archive search
    fetch_limit = min(5000, max(limit + offset, 5000 if (author_id or topic) else limit)) if filters_active else limit
```

Comment says 200; code fetches up to 5000 when `author_id` or `topic` is set. Either the cap was raised and the comment went stale, or a regression slipped in. Resolve it before anyone reasons about filtered-read cost from that comment.

---

### 5. Prototype patch (not pushed)

Constraints: label cardinality bounded by `key[0]` (6 values — never offsets or `author_id`); no prometheus import inside `load_guard`; metrics failure can never break a load; emit happens outside `_registry_lock`.

#### 5.1 `internal/message_intel/load_guard.py` — hook

```python
import logging

logger = logging.getLogger(__name__)

_recorder = None  # installed by internal.metrics

_STALE_STATES = frozenset({"stale_immediate", "stale_timeout", "stale_partial_timeout"})



def set_metrics_recorder(fn) -> None:
    """Install a (load_label, cache_state, seconds) sink. Optional; default off."""
    global _recorder
    _recorder = fn


def _load_label(key: Hashable) -> str:
    """Bounded label: first element of a tuple key, else 'scalar'."""
    if isinstance(key, tuple) and key:

        return str(key[0])
    return "scalar"


def _emit(label: str, state: str, started: float) -> float:
    elapsed = time.perf_counter() - started
    rec = _recorder
    if rec is not None:
        try:
            rec(label, state, elapsed)
        except Exception:
            logger.debug("load_guard metrics emit failed", exc_info=True)
    return elapsed


def _finish(label: str, started: float, data, state: str):
    elapsed_ms = round(_emit(label, state, started) * 1000.0, 3)
    meta = {"cache": state, "elapsed_ms": elapsed_ms}
    if state in _STALE_STATES:
        meta["stale"] = True
    return data, meta
```

#### 5.2 `guarded_load` — one exit per branch, and `LoadTimeout` finally classified

```python
def guarded_load(key, loader, *, ttl=None, wait_timeout=None):
    """Run loader at most once per TTL; concurrent callers wait or get stale."""
    if ttl is None:
        ttl = DEFAULT_TTL
    if wait_timeout is None:
        wait_timeout = DEFAULT_WAIT

    started = time.perf_counter()
    label = _load_label(key)
    pinned_leader = False
    need_wait = False
    hit_data = None
    hit_state = None
    slot: _Slot

    with _registry_lock:
        slot = _resolve_slot(key)
        if _fresh(slot, ttl):
            hit_data, hit_state = _isolate(slot.data), "hit"
        else:
            with slot.state_lock:
                if _fresh(slot, ttl):
                    hit_data, hit_state = _isolate(slot.data), "hit"
                elif slot.building:
                    if not slot.cold and slot.data is not None:
                        hit_data, hit_state = _isolate(slot.data), "stale_immediate"
                    else:
                        need_wait = True
                else:
                    slot.building = True
                    slot.build_done.clear()
                    _leader_registry_pin(slot)
                    pinned_leader = True
                    need_wait = False

    if hit_state is not None:
        return _finish(label, started, hit_data, hit_state)

    if need_wait:
        slot.build_done.wait(timeout=wait_timeout)
        if _fresh(slot, ttl):
            return _finish(label, started, _isolate(slot.data), "hit")
        if not slot.cold and slot.data is not None:
            return _finish(label, started, _isolate(slot.data), "stale_timeout")
        _emit(label, "timeout_error", started)
        raise LoadTimeout(f"message_intel load still in flight for key={key!r}")

    try:
        data = loader()
        with slot.state_lock:
            partial_timeout = (
                isinstance(data, dict)
                and bool((data.get("meta") or {}).get("load_timeout"))
            )
            if partial_timeout:
                if not slot.cold and slot.data is not None:
                    return _finish(label, started, _isolate(slot.data), "stale_partial_timeout")
                return _finish(label, started, _isolate(data), "partial_timeout_uncached")
            slot.data = data
            slot.at = time.time()
            slot.cold = False
        return _finish(label, started, _isolate(data), "refresh")
    finally:
        if pinned_leader:
            _unpin_slot(slot)
        with slot.state_lock:
            slot.building = False
        slot.build_done.set()
```

#### 5.3 `guarded_list_load` — stop discarding `_meta`

```python
def guarded_list_load(key, loader, *, ttl=None, wait_timeout=None, with_meta=False):
    data, meta = guarded_load(key, loader, ttl=ttl, wait_timeout=wait_timeout)
    out = [] if data is None else (data if isinstance(data, list) else list(data))
    return (out, meta) if with_meta else out
```

Backwards compatible: all six existing call sites keep their current return type.

#### 5.4 `internal/metrics.py` — the sink

```python
MESSAGE_INTEL_LOAD_SECONDS = Histogram(
    "subnet_message_intel_load_seconds",
    "Guarded message_intel load latency by load family and cache state",
    ["load", "cache"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
MESSAGE_INTEL_LOAD_TOTAL = Counter(
    "subnet_message_intel_load_total",
    "Guarded message_intel loads by load family and cache state",
    ["load", "cache"],
)


def _record_message_intel_load(load: str, cache: str, seconds: float) -> None:
    MESSAGE_INTEL_LOAD_TOTAL.labels(load=load, cache=cache).inc()
    MESSAGE_INTEL_LOAD_SECONDS.labels(load=load, cache=cache).observe(seconds)


def _install_load_guard_metrics() -> None:
    from internal.message_intel import load_guard

    load_guard.set_metrics_recorder(_record_message_intel_load)


_install_load_guard_metrics()
```

Open check: confirm `internal/metrics.py` is imported at app start in production, otherwise the recorder is never installed and the counters stay silent.

#### 5.5 Test sketch


```python
def test_guarded_load_meta_reports_elapsed_and_state(monkeypatch):
    recorded = []
    load_guard.set_metrics_recorder(lambda l, s, sec: recorded.append((l, s)))
    try:
        _data, meta = load_guard.guarded_load(("proof_rows", "/tmp/x"), lambda: [{"a": 1}])
        assert meta["cache"] == "refresh"
        assert meta["elapsed_ms"] >= 0.0
        _data, meta = load_guard.guarded_load(("proof_rows", "/tmp/x"), lambda: [{"a": 2}])
        assert meta["cache"] == "hit"
        assert [s for _l, s in recorded] == ["refresh", "hit"]
    finally:
        load_guard.set_metrics_recorder(None)
```

---

### 6. What this measures, and what would falsify my claim

With the counter live, `subnet_message_intel_load_seconds{load,cache}` separates cold from warm directly. The claim under test: **Tier 2 cold loads dominate and the hit path is negligible** — true only if `cache="hit"` p99 stays sub-millisecond. If hits are slow, the cost is in `_isolate()`, which shallow-copies every row on every hit (`load_guard.py:173-178`), not in SQLite — and the fix is entirely different.

`live_stats` stays unmeasured by this patch. It bypasses the guard, so it needs either a guard wrapper (freshness tradeoff: `last_message_age_seconds` would lag by the TTL) or separate timing on `_status_payload`. As the most-polled surface, it should be measured before any Tier 2 conclusion is drawn.

---

### 7. PRODUCTION MEASUREMENTS — §3 corrected

I fetched the live deployment (`subnet-dashboard.fly.dev`: `/metrics` and `/api/message-intel/status`) and measured instead of inferring. Two claims above do not survive.

#### 7.1 I was wrong that `/api/message-intel/status` is a hot path

The comment at `routes.py:194` calls it *"the most-polled status surface on the homepage hydrate path."* Production:

| Measurement | Value |
|---|---|
| Process uptime at scrape | 8,040.7 s (2h14m) |
| `request_processing_time_count{path="/api/message-intel/status"}` | **1** |
| Implied rate | 0.45 requests/hour |
| `request_processing_time_sum` | 15.50 ms |

Called **once in two hours**, not polled. The comment is aspirational or stale, and I built a hot-path narrative on it without checking. Someone opening a page pays ~15 ms — not a cost problem.

#### 7.2 The table is small, which makes the scan cheap

- `total_messages` = **5,812**
- `high_conviction_count` = **1,817** = **31.3%**

The second number also corrects an earlier claim of mine in this thread — that most rows fail the `conviction >= 60` gate and "can never influence either answer." Nearly a third pass it. Selective, not prohibitive. At 5.8k rows the three aggregates are ~15 ms together with `listener_status()`. Not a crisis now; linear-growth risk, and still worth caching because the cost is pure repetition.

#### 7.3 Real cost of the 3000-row build

| Metric | Value |
|---|---|
| `subnet_score_snapshot_build_wall_seconds` | **61.745 s** (source not recorded in this packet; the 2026-10-21 web scrape reads `-1.0`, unavailable) |
| `subnet_score_snapshot_publish_wall_seconds` | **0.0083 s** (the 2026-10-21 web scrape reads `-1.0`) |
| Ratio | **withdrawn.** The printed operands give ~7,439×, and 0.0083 is rounded, so no four-digit ratio is supported. |

If the 61.7 s reading holds, the rows cost lives almost entirely in that build stage. It is unverified: the 2026-10-21 web scrape reads `-1.0` (unavailable) for both gauges, so a worker-side read is needed before anyone defends it.


#### 7.4 The monitoring surface reports "everything stopped" while the system runs

```
subnet_scheduler_running{scheduler="resolver"}     0.0
subnet_scheduler_running{scheduler="adversarial"}  0.0
subnet_scheduler_running{scheduler="apscheduler"}  0.0
subnet_scheduler_last_ok{scheduler="resolver"}     1.0
subnet_scheduler_last_ok{scheduler="adversarial"}  0.0
subnet_scheduler_job_count                         0.0
subnet_sync_running                                0.0
subnet_sync_last_ok                                0.0
```

The 2026-10-21 scrape shows the readiness report fresh but the score snapshot 12.0 h old, so "demonstrably alive" is withdrawn for the snapshot path:

```
readiness_builds_total                    24
readiness_report_age_seconds              18.60
subnet_score_snapshot_age_seconds         43161.70  (12.0 h)
subnet_score_snapshot_build_wall_seconds  -1.0      (unavailable, 2026-10-21 scrape)
```

**Root cause — absent state renders as a hard zero:**

- `metrics.py:212` — `SCHEDULER_RUNNING.labels(...).set(1 if info.get("running") else 0)` — a missing key sets 0, identical to a stopped scheduler.
- `metrics.py:227` — `SCHEDULER_JOB_COUNT.set(js.get("job_count", 0))`.
- `metrics.py:193` — `SYNC_RUNNING.set(1 if sync.get("background_running") else 0)`.
- `metrics.py:201-202` — `SOURCE_STALE` set only when `is_stale is not None`; otherwise the prior scrape's value persists.
- `metrics.py:160-166` — `_set_optional` skips None, so an age gauge holds whatever it last held, forever.

That last one explains `subnet_source_age_seconds{source="soul_map"} = 4,642,227` — **53.7 days** on 2026-10-21 (the earlier reading was 4,447,452, 51.5 days) — beside `subnet_source_stale{source="soul_map"} = 1.0`. Either soul_map genuinely has not been written in almost eight weeks or the gauge is a zombie pinning a value nobody reset. Both are equally invisible.

This is the most serious defect in the audit, and it is a few lines of dashboard code from being fixed: a gauge that cannot distinguish *unknown* from *healthy* is worse than no gauge, because it is read as evidence.

#### 7.5 Other live readings

- `coverage_complete = 0.0` and `coverage_published = 0.0` on 2026-10-21. The earlier reading (`coverage_published = 1.0` beside `coverage_complete = 0.0`) does not reproduce, so the "publishing an incomplete snapshot" claim is withdrawn until it is re-measured.
- `horizon_succeeded{hour}=0` / `copied{hour}=40`; `succeeded{day}=40` / `copied{day}=0`. **Not a bug** — `snapshot_coverage.py:464-467` returns the copied count only for `hour`, deliberately (checked at the pin). The 2026-10-21 scrape reads all four horizon gauges as 0.0, so the values above do not reproduce.
- `chain_rpc_requests_total` on 2026-10-21 = 20 `ok` / **4 `rate_limited`** / 0 `cooldown_skip` (one endpoint, one method), 17% rate-limited. The earlier reading (132 / 35 / 1, 21%) does not reproduce.
- `subnet_live_refresh_complete = 0.0` with `subnet_live_stale = 0.0` — fresh but partially refreshed.
- `subnet_source_age_seconds{price_cache}` = 1,026 s (17.1 min) on 2026-10-21, flagged stale. The earlier 7,180 s (2.0 h) reading does not reproduce.

#### 7.6 Deployment topology — the patch works as written

`fly.toml`: single `[processes] web = "sh ./scripts/fly_web_entrypoint.sh"`, `min_machines_running = 1`, with an explicit comment that a Fly worker process group would spawn a second machine and split the volume. `Procfile`: `uvicorn asgi_entry:app` — no `--workers`, so one worker. `server.py` imports `internal.metrics`, so it loads at start.

**Corrected 2026-10-21:** the web machine runs a second Python process. `scripts/fly_web_entrypoint.sh:34` (pin) starts the inline worker with `nice -n 10 env RUN_MODE=worker … python -m internal.worker &`. That is a separate interpreter with its own default registry. Web `/metrics` is served by the web process alone, and `PROMETHEUS_MULTIPROC_DIR` is not set, so the worker's counters are never scraped. The open question in §5.4 is open again. At live `4560c10d` the same start is at line 90 (`setsid sh -c "exec $INLINE_WORKER_LAUNCH" &`); the second process is unchanged.

Consequence: the guard counters below show request-path loads from the web process only. Background loads that run in the worker do not appear on `/metrics` until the worker's registry is exported some other way. That is a design change, not a caveat.

---

### 8. What the evidence supports

| Claim | Verdict |
|---|---|
| `build_cost` cannot see Tier 2 | **Confirmed** — code and live scrape; zero `message_intel` metrics in production |
| "~1% overhead" | **Unfounded** — not measured, not derivable |
| Tier 2 is cheap because cached | **Supported** — 15 ms end-to-end, 5.8k rows, TTL guard present |
| `/api/message-intel/status` is a hot path | **Refuted** — 1 call in 2h14m |
| Most rows fail the conviction gate | **Refuted** — 31.3% pass |
| Scheduler gauges are trustworthy | **Refuted** — `running` and `job_count` read 0 while the pipeline runs, and resolver `last_ok` reads 1 on 2026-10-21 |
| A metric must distinguish unknown from zero | **Confirmed** — current gauges conceal a live system |

---

### 9. Does this need a full overhaul? No — and here is why not


The evidence points to a **truth problem**, not a structure problem.

**What is good, and would not survive a rewrite:**

- `load_guard` is careful: single-flight per key, leader pinning so an in-flight slot cannot be LRU-evicted (`:41-61, 84-97`), stale-immediate for waiters on a hung leader, refusal to cache cold partial timeouts (`:233-239`), copy isolation so callers cannot mutate cached rows (`:173-178`).
- `tests/test_message_intel_single_flight_cache.py` and `test_build_cost.py` cover the invariants, including the LRU-pin race.
- The single-machine, single-volume, no-worker-group topology is a deliberate anti-split-brain decision, commented as such.
- Deployments are gated through CI with secrets checks and live verification.

**What is broken, and a rewrite would not fix by itself:**

1. **Gauges conflate unknown with zero.** The most consequential finding. `None → 0` mapping will re-emerge in any rewrite unless the rule is stated once and enforced.
2. **Instrumentation covers the path someone was curious about that afternoon** (`conviction`, `rpc`), not the system. `build_cost` can only ever be opened by one function.
3. **Comments describe behaviour the code dropped** — `engine.py:396` says 200, `:400` fetches 5000.
4. **Documented intent is not asserted.** "Most-polled" lives in a comment and no test, so nothing catches it being false.

**The argument against a rewrite is quantitative:** the snapshot pipeline was measured at 61.7 s of build and 8 ms of publish (source not recorded here; both gauges read `-1.0` on the 2026-10-21 web scrape). You cannot redesign a system whose cost distribution you have only just measured, and the profile says one stage dominates everything anyone has been arguing about.

**The narrow fix is a truth layer, in order:**


1. **Three-state gauges** (unknown / healthy / failing), or a companion `*_available` gauge. Highest value per line in the repo.
2. **Instrument the guard seam** (§5) — the only place Tier 2's cache behaviour becomes observable, and it already returns the classification.
3. **Delete or generalize `build_cost`.** Two kinds, one window, one caller; either it grows a kind registry or it goes and the guard counter subsumes it. Keeping it as-is preserves a false sense of coverage.
4. **Encode the drifts.** A test asserting `fetch_limit` matches the documented cap; a test asserting the status endpoint's polling assumption. Comments that lie should fail CI.

Days of focused work on ~200 lines — against a rewrite measured in weeks, betting on a system currently telling you it is down.

---

### 10. The proposed fix — written out, **NOT applied**

> **Status: nothing committed. Nothing pushed. No branch cut.**
> Everything below is a patch proposal against pin `3a65d34ac46a28395559310f21db013b4581c645`.
> It exists so the change can be reviewed and argued with before a single line moves.

#### 10.0 The one rule all four fixes obey

A metric has three states, and the code must never collapse two of them:

| State | Meaning | Encoding |
|---|---|---|
| **unknown** | the subsystem never reported | `-1` |
| **failing** | it reported, and it is bad | `0` |
| **healthy** | it reported, and it is fine | `1` |

`-1` is not my invention. `metrics.py:32` already defines `LIVE_REFRESH_COMPLETE_UNAVAILABLE = -1.0` and `metrics.py` already documents several gauges as "-1 when unavailable". **The convention exists in the file; it is simply not applied to the gauges where it matters.** That is the whole fix, and it is why it is small.

#### 10.1 Fix A — three-state gauges (`internal/metrics.py`)

**Defect:** `metrics.py:212` reads `set(1 if info.get("running") else 0)`. A missing key and a stopped scheduler both produce `0`. Same at `:193` (sync running) and `:226-227` (apscheduler). `:196` (sync last ok) and `:218` (failures) are guarded by `is not None`, so an absent key leaves the gauge at its last value instead of writing `0`. And `_set_optional` at `:160-166` **returns early on None**, so every age gauge pins its last value indefinitely — the `soul_map` 51.5-day zombie. **Premise check (2026-10-21).** The code claim holds at the pin: a missing key and a stopped scheduler both emit `0` (`metrics.py:212`, `:226`). The live zeros in §7.4 (lines 1470–1477) do not support the meaning the packet gives them. The web process runs with `BACKGROUND_ON_WEB=off` (`fly.toml:35`) and does not own the scheduler or sync state, so those zeros mean 'not running in this process', not 'stopped' or 'failing'. For `subnet_sync_last_ok`, the gauge is set only when the key is present (`metrics.py:195–196`), so the `0` may be the gauge's untouched default. Fix A's `UNAVAILABLE = -1` for an absent state would make that absence visible. It would not put the worker's state on web. That needs the separate change §7.6 describes.

```diff
@@ internal/metrics.py

+UNAVAILABLE = -1.0
+
+
+def _tri(value: Any) -> Optional[float]:
+    """Map a state field to 1/0, or None when the field is absent (= unknown)."""
+    if value is None:
+        return None
+    return 1.0 if value else 0.0
+
+
+def _set_tri(gauge: Gauge, value: Any, labels: Optional[Dict[str, str]] = None) -> None:
+    """Set 1/0, or -1 when unknown. Never silently leaves a stale value in place."""
    target = gauge.labels(**labels) if labels else gauge
+    tri = _tri(value)
+    target.set(UNAVAILABLE if tri is None else tri)
+
@@ def _set_optional
-    if value is None:
-        return
+    # Unknown is a value. Skipping the write pins the previous scrape forever,
+    # which is how subnet_source_age_seconds{soul_map} sat at 51.5 days (53.7 days on 2026-10-21).
+    if value is None:
+        value = UNAVAILABLE
     if labels:
         gauge.labels(**labels).set(value)
     else:
         gauge.set(value)
@@ def refresh_from_state
-        SYNC_RUNNING.set(1 if sync.get("background_running") else 0)
+        _set_tri(SYNC_RUNNING, sync.get("background_running"))
         last_ok = sync.get("last_sync_ok")
-        if last_ok is not None:
-            SYNC_LAST_OK.set(1 if last_ok else 0)
+        _set_tri(SYNC_LAST_OK, last_ok)
         freshness = sync.get("freshness") or {}
         for source in _SOURCES:
             info = freshness.get(source) or {}
             _set_optional(SOURCE_AGE_SECONDS, info.get("age_seconds"), {"source": source})
-            if info.get("is_stale") is not None:
-                SOURCE_STALE.labels(source=source).set(1 if info.get("is_stale") else 0)
+            _set_tri(SOURCE_STALE, info.get("is_stale"), {"source": source})
@@ scheduler loop
-            SCHEDULER_RUNNING.labels(scheduler=scheduler).set(1 if info.get("running") else 0)
+            _set_tri(SCHEDULER_RUNNING, info.get("running"), {"scheduler": scheduler})
             last_ok = info.get("last_run_ok")
-            if last_ok is not None:
-                SCHEDULER_LAST_OK.labels(scheduler=scheduler).set(1 if last_ok else 0)
+            _set_tri(SCHEDULER_LAST_OK, last_ok, {"scheduler": scheduler})
             failures = info.get("consecutive_failures")
-            if failures is not None:
-                SCHEDULER_FAILURES.labels(scheduler=scheduler).set(failures)
+            SCHEDULER_FAILURES.labels(scheduler=scheduler).set(
+                UNAVAILABLE if failures is None else failures
+            )
@@ apscheduler
-        SCHEDULER_RUNNING.labels(scheduler="apscheduler").set(1 if js.get("running") else 0)
-        SCHEDULER_JOB_COUNT.set(js.get("job_count", 0))
+        _set_tri(SCHEDULER_RUNNING, js.get("running"), {"scheduler": "apscheduler"})
+        SCHEDULER_JOB_COUNT.set(
+            UNAVAILABLE if js.get("job_count") is None else js["job_count"]
+        )
```

**What this changes in production, immediately:** every scheduler gauge currently reading `0.0` becomes `-1`, and the dashboard stops reporting "everything stopped". The `soul_map` age stops claiming a precise 51.5-day fact it cannot support and reports `-1`.

**Cost:** ~45 lines changed in one file. **Risk:** any alert rule matching `== 0` now needs `== -1` added as a distinct case — that is the point, but it must be checked before merge. **This is the fix to do first.**

#### 10.2 Fix B — instrument the guard seam (`load_guard.py` + `metrics.py`)

**Defect:** `build_cost` cannot see Tier 2 because it only records while a build is active (§5). `load_guard` already computes the exact classification and throws it away: `{"cache": "hit"}`, `"stale_immediate"`, `"stale_timeout"`, `"stale_partial_timeout"`, `"partial_timeout_uncached"`, `"refresh"`, and `LoadTimeout`. Counting them is the cheapest possible observation of Tier 2's real behaviour.

```diff
@@ internal/metrics.py
+MESSAGE_INTEL_LOAD_TOTAL = Counter(
+    "message_intel_load_total",
+    "message_intel guarded loads by outcome (hit/refresh/stale/timeout)",

+    ["outcome"],
+)
+MESSAGE_INTEL_LOAD_SECONDS = Histogram(
+    "message_intel_load_seconds",
+    "Wall seconds for a message_intel guarded load by outcome",
+    ["outcome"],
+    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
+)
```

```diff
@@ internal/message_intel/load_guard.py
+from internal.metrics import MESSAGE_INTEL_LOAD_SECONDS, MESSAGE_INTEL_LOAD_TOTAL
+
...
@@ def guarded_load
     """Run loader at most once per TTL; concurrent callers wait or get stale."""
+    started = time.perf_counter()
+
+    def _finish(outcome: str):
+        try:
+            MESSAGE_INTEL_LOAD_TOTAL.labels(outcome=outcome).inc()
+            MESSAGE_INTEL_LOAD_SECONDS.labels(outcome=outcome).observe(
+                time.perf_counter() - started
+            )
+        except Exception:
+            pass
+
     if ttl is None:
         ttl = DEFAULT_TTL
@@
         if _fresh(slot, ttl):
-            return _isolate(slot.data), {"cache": "hit"}
+            _finish("hit")
+            return _isolate(slot.data), {"cache": "hit"}
         with slot.state_lock:
             if _fresh(slot, ttl):
-                return _isolate(slot.data), {"cache": "hit"}
+                _finish("hit")

+                return _isolate(slot.data), {"cache": "hit"}
             if slot.building:
                 if not slot.cold and slot.data is not None:
-                    return _isolate(slot.data), {
+                    _finish("stale_immediate")
+                    return _isolate(slot.data), {
                         "cache": "stale_immediate",
                         "stale": True,
                     }
@@
     if need_wait:
         slot.build_done.wait(timeout=wait_timeout)
         if _fresh(slot, ttl):
-            return _isolate(slot.data), {"cache": "hit"}
+            _finish("hit_after_wait")
+            return _isolate(slot.data), {"cache": "hit"}
         if not slot.cold and slot.data is not None:
-            return _isolate(slot.data), {"cache": "stale_timeout", "stale": True}
+            _finish("stale_timeout")
+            return _isolate(slot.data), {"cache": "stale_timeout", "stale": True}
+        _finish("timeout")
         raise LoadTimeout(f"message_intel load still in flight for key={key!r}")
@@
             if partial_timeout:
                 if not slot.cold and slot.data is not None:
-                    return _isolate(slot.data), {
+                    _finish("stale_partial_timeout")
+                    return _isolate(slot.data), {
                         "cache": "stale_partial_timeout",
                         "stale": True,
                     }
-                return _isolate(data), {"cache": "partial_timeout_uncached"}
+                _finish("partial_timeout_uncached")
+                return _isolate(data), {"cache": "partial_timeout_uncached"}
             slot.data = data
             slot.at = time.time()
             slot.cold = False
-        return _isolate(data), {"cache": "refresh"}
+        _finish("refresh")
+        return _isolate(data), {"cache": "refresh"}
```

**Why this answers the original Tier 2 question better than any benchmark:** after one day you can read the hit rate, the p99 load duration, and the timeout count *for every Tier 2 consumer*, from production, without touching `build_cost` or guessing at overhead.

**Caveat to state plainly:** the worker is a separate process (§7.6), so these counters show request-path loads from the web process only. The background Tier 2 cost stays invisible until the worker's registry is exported. The `outcome` label would not separate the two in any case, and I am not inventing a label to pretend otherwise.

#### 10.3 Fix C — make `build_cost` dual-mode (`internal/build_cost.py`)

**Defect:** `record()` returns immediately when `_active is None`. Outside a build window — i.e. for every request-path and standalone call — the cost is discarded. That is precisely why Tier 2 was invisible.

```diff
@@ internal/build_cost.py
 import threading
 import time
 from typing import Any, Dict, Optional
 
+from internal.metrics import (
+    BUILD_COST_SECONDS_TOTAL,
+    BUILD_COST_CALLS_TOTAL,
+)
+
 _lock = threading.Lock()
 _active: Optional[Dict[str, Any]] = None
+_KNOWN_KINDS = ("conviction", "rpc")
@@ def record
 def record(kind: str, seconds: float) -> None:
+    # Always observable, whether or not a build window is open.
+    try:
+        BUILD_COST_CALLS_TOTAL.labels(kind=kind).inc()
+        BUILD_COST_SECONDS_TOTAL.labels(kind=kind).inc(seconds)
+    except Exception:
+        pass
     with _lock:
         if _active is None:
             return
-        if kind == "conviction":
-            _active["conviction_queries"] += 1
-            _active["conviction_query_seconds"] += seconds
-        elif kind == "rpc":
-            _active["rpc_calls"] += 1
-            _active["rpc_seconds"] += seconds
+        if kind not in _KNOWN_KINDS:
+            _active.setdefault("other", {})[kind] = (
+                _active.setdefault("other", {}).get(kind, 0.0) + seconds
+            )
+        if kind == "conviction":
+            _active["conviction_queries"] += 1
+            _active["conviction_query_seconds"] += seconds
+        elif kind == "rpc":
+            _active["rpc_calls"] += 1
+            _active["rpc_seconds"] += seconds
```

```diff
@@ internal/metrics.py
+BUILD_COST_CALLS_TOTAL = Counter(
+    "build_cost_calls_total", "Recorded build-cost calls by kind (build- or request-path)",
+    ["kind"],
+)
+BUILD_COST_SECONDS_TOTAL = Counter(
+    "build_cost_seconds_total", "Recorded build-cost seconds by kind (build- or request-path)",
+    ["kind"],
+)
```

**The design point:** an unknown `kind` no longer disappears. It lands in an `other` bucket and in the counter, so a new Tier 2 call site that forgets to register itself is *visible as a growing `other`*, not as silence. Silent no-ops are how this whole audit started.

#### 10.4 Fix D — the drift tests (the part that stops it recurring)

Three tests, each written to fail against `3a65d34` today:

```python
# tests/test_metrics_three_state.py

def test_scheduler_gauge_is_unknown_when_state_key_absent(monkeypatch):
    """A state reader that omits 'running' must not read as 'stopped'."""
    monkeypatch.setattr(metrics, "_resolver_state", lambda: {})
    metrics.refresh_from_state()
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="resolver")._value.get() == -1.0
    # and a real stop still reads 0
    monkeypatch.setattr(metrics, "_resolver_state", lambda: {"running": False})
    metrics.refresh_from_state()
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="resolver")._value.get() == 0.0

def test_age_gauge_does_not_pin_previous_scrape(monkeypatch):
    """None must overwrite, not skip — the soul_map zombie."""
    monkeypatch.setattr(metrics, "_SOURCES", ("x",))
    monkeypatch.setattr("internal.freshness.get_sync_state",
                        lambda: {"freshness": {"x": {"age_seconds": 10.0}}})
    metrics.refresh_from_state()
    assert metrics.SOURCE_AGE_SECONDS.labels(source="x")._value.get() == 10.0
    monkeypatch.setattr("internal.freshness.get_sync_state",
                        lambda: {"freshness": {"x": {}}})
    metrics.refresh_from_state()
    assert metrics.SOURCE_AGE_SECONDS.labels(source="x")._value.get() == -1.0

# tests/test_build_cost_outside_window.py

def test_record_outside_build_window_still_increments():
    """Tier 2 cost must be observable with no build active."""
    build_cost.end() if build_cost._active else None
    before = metrics.BUILD_COST_CALLS_TOTAL.labels(kind="conviction")._value.get()
    build_cost.record("conviction", 0.25)
    assert metrics.BUILD_COST_CALLS_TOTAL.labels(kind="conviction")._value.get() == before + 1

# tests/test_engine_fetch_limit_matches_contract.py

def test_documented_cap_matches_fetch_limit():
    """engine.py's docstring says 200; the fetch must not say 5000."""
    src = (ROOT / "internal/message_intel/engine.py").read_text()

    assert "5000" not in src.split("def list_messages")[1].split("def ")[0], \
        "fetch limit drifted from the documented cap of 200"
```

The third test is deliberately crude. It exists because `engine.py:396` documents 200 and `engine.py:400` fetches 5000, and nothing caught it. A crude test that fails on the real mistake beats an elegant one that never ran.

#### 10.5 What I am explicitly *not* recommending

**Caching `/api/message-intel/status` — dropped.** §7.1 measured 1 call in 2h14m at 15.5 ms. My earlier §3 case for a 30-second TTL cache was built on a code comment, not on traffic. On the evidence, adding a cache here buys nothing and adds a staleness surface to the one endpoint whose entire job is reporting freshness. **Recommendation: leave it alone; update the misleading comment instead.**

This is worth naming: of the fixes I originally proposed, production data justified removing one.


#### 10.6 Order and cost

| # | Fix | Files | Lines | Risk | Do first? |
|---|---|---|---|---|---|
| A | Three-state gauges | `internal/metrics.py` | ~45 | Alert rules matching `==0` need review | **Yes** |
| B | Guard counters | `load_guard.py`, `metrics.py` | ~35 | None (additive) | Yes |
| C | `build_cost` dual-mode | `build_cost.py`, `metrics.py` | ~30 | None (additive) | Yes |
| D | Drift tests | 3 new files | ~50 | None (test-only) | With A |
| — | Status cache | — | — | — | **No — dropped** |

Total: **~160 lines across 5 files**, all additive or mechanically substitutable, no schema change, no new process, no dependency. A and D together are what stop the system lying about itself.

**None of it is applied.** Awaiting a decision.

---

### 11. Audit ledger — every claim this packet corrected

Kept here so the packet does not depend on the conversation that produced it.

**Moved to Part X.1.** Provenance only — the body states the current version of each of these nine items.

---

## Part IV — Scoring Universe Contract (design pass)

*Originally `scoring-universe-contract-2026-10-18.md`. Design only — nothing applied. Pin `3a65d34a`.*

**Repository:** `cryptoreporthub/subnet-dashboard` · **Pin:** `3a65d34ac46a28395559310f21db013b4581c645`
**Date:** 2026-10-18 · **Mode:** /architect · **Status:** design only — nothing applied, nothing committed.

This is the design pass that the audit packet never had. Its job is to make the *fix* uncopyable-wrong: not "here are the 8 edits", but "here is the one shape every edit must fit".

## Phase ledger

| Phase | State | Note |
|---|---|---|
| **A — Ground** | done | 9 modules read at the pin; 8 selection sites located by line |
| **B — Sketch** | done | 3 structurally distinct shapes, screened |
| **C — Agree** | **waiting on you** | checkpoint requested; nothing proceeds without it |
| **D — Implement** | not started | |
| **E — Scrap** | armed | triggers listed at the end |

---

## Phase A — Ground: what the code actually is

### The seam

One question decides most of the audit: *which subnets does a scoring pass see?* That answer is set in **eight places**, from **four knobs**, with **three different defaults** — and one of them reaches across a module boundary into the app entrypoint.

| # | Site | file:line | Limit expression | Effective default |
|---|---|---|---|---|
| 1 | wrapper default | `server.py:932` | `cap_subnets_for_scoring(subnets, limit, default_limit=TOP_SCORING_UNIVERSE)` | **20** (`TOP_SCORING_UNIVERSE` default `"20"`, `server.py:647`) |
| 2 | homepage shell | `server.py:1066` | `min(24, TOP_SCORING_UNIVERSE)` | 20 |
| 3 | spotlight | `server.py:1214` | no limit → wrapper default | 20 |
| 4 | simivision | `server.py:2946` | no limit → wrapper default | 20 |
| 5 | hour pick | `server.py:3363` | `min(24, TOP_SCORING_UNIVERSE)` | 20 |
| 6 | pick scheduler | `internal/council/pick_scheduler.py` `_load_capped_subnets` | `min(PICK_SCHEDULER_UNIVERSE_CAP, TOP_SCORING_UNIVERSE)` | 20 |
| 7 | daily pick creation | `internal/council/daily_pick_engine.py` `_subnets_for_pick_creation` | `min(sched_cap="24", top="40")` | **24** — different `TOP` default |
| 8 | snapshot build | `internal/council/score_snapshots.py:667` | `_snapshot_subnet_cap()` | **0** (env) — but **40** in worker mode |

Site 7 sets `TOP_SCORING_UNIVERSE` to `"40"`; every other site reads `20`. Site 8 returns `0` when the env is unset — *unless* `is_worker_mode()`, where it silently becomes 40. So the same process graph runs at 20, 24, 40, or "everything" depending on which door you enter. That is the audit's "40-cap has two defaults" finding, confirmed and larger than stated: **it is four.**

### What the cap function can do

`internal/subnets/scoring_cap.py` (3,601 B) exports one function:

    def cap_subnets_for_scoring(subnets, limit=None, *, default_limit=40) -> List[Dict]

    if not subnets or len(subnets) <= cap: return list(subnets)
    try:
        ranked = rank_subnets_by_snapshot(subnets, horizon="day")   # from council.score_snapshots
        if ranked: return ranked[:cap]
    except Exception:
        pass
    # heuristic fallback
    mega = env_int("SCORING_CAP_MEGA_CEILING_RANK", 10)
    pool = _heuristic_hunt_pool(subnets, mega_ceiling_rank=mega, mid_min=11, mid_max=75)
    return pool[:cap]

Three properties matter:

1. **It imports `rank_subnets_by_snapshot` from the module that calls it.** `score_snapshots.py:672` does `from server import _cap_subnets_for_scoring`, which imports `scoring_cap`, which imports back into `score_snapshots`. A real cycle, load-order-sensitive, and it works today only because every hop is a lazy function-level import.
2. **Its meaning depends on data availability.** With a fresh snapshot it promotes *any* netuid by rank. Without one it drops everything at `marketcap_rank <= 10` — permanently, not by rank pressure. The exceptions are swallowed (`except Exception: pass`), so a snapshot read that throws silently switches selection policy.
3. **Unranked is `10_000`, not `None`.** Missing marketcap rank sorts as "low cap", which is into the hunt band. Absent data is silently promoted.

### What truncation is recorded as

    # score_snapshots.py
    cap = _snapshot_subnet_cap()
    capped_out = 0
    if cap > 0 and len(subnets) > cap:
        subnets = _cap_subnets_for_scoring(subnets, limit=cap)
        capped_out = pre_cap_len - len(subnets)
        selection_policy = "rank_cap"

    # snapshot_coverage.py:359
    complete = bool(published and membership_ok and horizons_complete and capped_out == 0)

The audit's R9 is correct and precise: **while any cap binds, `complete` is structurally false.** The coverage block knows a *count* was dropped and nothing else — not which netuids, not why. A number is the weakest possible record: it cannot be joined against the universe, cannot be replayed, cannot tell a budget drop from a filter drop.

`scored_complete` (`snapshot_coverage.py:243`) requires `succeeded_set == expected_set`, so the two conditions are redundant: a cap already guarantees failure twice over.

### The Telegram path

    # scoring_context.py — once per scoring batch
    ctx["telegram_conviction_rows"] = _conviction_rows()          # up to 3000 rows
    ctx["telegram_calibration_health"] = calibration_health(...)

    # state_vector.py:1900 — once per subnet
    calibration_for_subnet(netuid, conviction_rows=..., calibration_health_snapshot=...)
    total += telegram_calibration["adjustment_points"]

    # calibration.py — calibration_for_subnet
    for row in rows:                       # ALL rows, per subnet
        proof = classify_call(row)
        timestamp = _parse_ts(...)
        if not proof["eligible"] or timestamp is None or timestamp < cutoff: continue
        if wanted not in _netuids_from_row(row): continue     # netuid filter LAST
    applied = health["active"] and ...
    # health["active"] is False whenever cfg["enabled"] is False
    # cfg["enabled"] = _flag("TELEGRAM_EVIDENCE_CALIBRATION"), default off

Confirmed exactly as the audit stated: **the scan happens before the netuid filter, and the result is guaranteed `0.0` whenever the flag is off.** The hoist in `scoring_context.py` moved the *DB read* out of the loop but left the *row loop* in it — N × 3000 property reads, per cycle, for a provable zero. Note also that the hoist loads 3,000 rows per batch even when the flag is off, so the remaining waste is a function of the flag, not of N.


### What I did not verify

- `PICK_SCHEDULER_UNIVERSE_CAP`'s module default in `pick_scheduler.py` — I read its use, not its declaration.
- I did not re-read Part III's production measurements this pass, so the cost-per-subnet numbers below are the audit's, not re-derived.
- I did not run anything against production. No numbers here are measurements made by me today.

---

## Phase B — three shapes

The design question is not "where do we delete the cap". It is: **what is the type of "which subnets get scored"?** Today the answer is `List[Dict]` and an implicit int — which is why eight sites disagree. Three shapes, deliberately whole-shape alternatives:

### Candidate A — Delete the knob

No selection function at all. Every consumer scores the universe it was handed. Where a request-path genuinely cannot afford it, the caller slices locally.

    - delete internal/subnets/scoring_cap.py
    - delete 7 call sites; coverage loses capped_out entirely
    + each hot path gets an inline [:k] with a comment

Smallest diff, zero new concepts. **Fails the red-flag screen**: seven independent slicings is precisely the shape that produced four defaults. The next agent copies the nearest example — and the nearest example will be `[:20]`.

### Candidate B — Selection is a value, budget is a parameter

One type, one function, constructed at the process boundary, passed down.

    # internal/subnets/scoring_budget.py  — owns env parsing, owns ranking, imports nothing from council
    @dataclass(frozen=True)
    class ScoringBudget:
        kind: Literal["full", "deadline"]
        seconds: float | None = None
        def is_full(self) -> bool: ...

        @staticmethod
        def from_env(mode: str) -> "ScoringBudget": ...   # the ONLY env read

    class Dropped(NamedTuple):
        netuid: int
        reason: Literal["deadline", "unscored_error"]

    @dataclass(frozen=True)
    class Selection:
        rows: list[dict]
        dropped: list[Dropped]          # not a count — the actual netuids
        policy: str                     # "full" | "deadline"
        @property
        def complete(self) -> bool: return not self.dropped

    def select_universe(rows, budget: ScoringBudget, *, ranker=None) -> Selection

Callers never see a number. `build_coverage_block` takes `Selection`, not `capped_out: int`. The hunt band and its three envs die with the old module; no replacement.

### Candidate C — Deadline only

No count anywhere. The scorer runs until a wall-clock deadline, then marks what it missed.

    def score_universe(rows, deadline: float) -> tuple[list[Row], list[Unscored]]
    # Row.scored = False, Row.reason = "deadline"

Truest to "no universe cap", smallest surface, and self-limiting under load — which is what the four caps were actually trying to be. **Costs**: non-determinism on shared CPU (same input, different output set), so tests need a fake clock, and "N in → N out" stops being provable.

### Screen

| Red flag | A | B | C |
|---|---|---|---|
| Next agent copies nearest example correctly | ✗ 7 slicings | ✓ one call | ✓ one call |
| Callers must know internal rules | ✓ no | ✓ no | ~ needs clock semantics |
| Absent data silently promoted | n/a | ✓ type forbids | ✓ |
| Truncation observable & replayable | ✗ | ✓ netuids + reason | ✓ |
| Deterministic / unit-testable | ✓ | ✓ | ✗ without injected clock |
| Subscription point for env | ✗ scattered | ✓ one | ✓ one |
| New concepts introduced | 0 | 2 | 1 |

B wins on interface depth: two types replace four knobs, eight call sites, one exception-swallowing policy switch, and a module cycle. C wins on surface area but buys it with determinism, which is the property `coverage_complete` depends on.

### Synthesis

**B is the spine, with C's deadline as the only non-full budget, and A's subtraction as step one.**

The decisive fact from Phase A: the count cap existed to compensate for the Telegram scan. That scan is provably zero-effect and is being deleted in the same change. So the honest sequencing is *remove the compensation after removing the cost* — and keep exactly one limit, a deadline, on request-path callers only, never on the snapshot.

---

## The contract to implement

### Usage sketch (written first; types derived from it)

    # score_snapshots.py — the build. Full universe, no budget.
    selection = select_universe(subnets, ScoringBudget.full(), ranker=rank_subnets_by_snapshot)
    ...
    coverage = build_coverage_block(..., selection=selection, ...)

    # server.py — homepage shell. Bounded, and says so.
    selection = select_universe(subnets, ScoringBudget.deadline(2.5))
    subnets = selection.rows

    # pick_scheduler.py / daily_pick_engine.py — no import from server.
    selection = select_universe(subnets, budget_from_config())

There is no `_cap_subnets_for_scoring`. There is no `TOP_SCORING_UNIVERSE`.


### Module map

| Unit | Owns | May import |
|---|---|---|
| `internal/subnets/scoring_budget.py` **(new)** | `ScoringBudget`, `Selection`, `Dropped`, `select_universe`, `from_env` | stdlib only; ranker injected |
| `internal/subnets/scoring_cap.py` **(deleted)** | — | — |
| `internal/council/score_snapshots.py` | snapshot build | `scoring_budget` — **not** `server` |
| `internal/council/snapshot_coverage.py` | coverage from `Selection` | `scoring_budget` (types only) |
| `server.py` | env → budget at boot | `scoring_budget` |
| `internal/council/pick_scheduler.py`, `daily_pick_engine.py` | receive budget | `scoring_budget` — **not** `server` |

The cycle is broken by construction: the ranker is a parameter, so `scoring_budget` imports nothing from council and the arrow points one way.

### Migration order — five units, each ending verifiable

1. **Subtract dead weight first.** Delete the unused `SCORE_SNAPSHOT_MAX_SUBNETS` module constant (`score_snapshots.py:38`) — the function reads the env directly; the constant is referenced nowhere else in the file. Delete `_heuristic_hunt_pool` / `_focus_tier` / the three `SCORING_CAP_*` envs with their tests. Verify: grep finds no importer, suite green.
2. **Add the type, unwired.** `scoring_budget.py` + tests (N in → N out for full; dropped netuids named for deadline; no promotion of missing rank). Production behavior unchanged — nothing calls it yet.
3. **Convert the snapshot path.** `select_universe` with `full()`; coverage takes `Selection`. Verify: a build at the pin's universe returns exactly the membership count, and `complete` is now reachable — the first cycle it can be true is the proof.
4. **Convert the four request paths**, each in its own commit, each with its latency budget named at the call site. Delete `_cap_subnets_for_scoring` when the last caller leaves — not before, and not kept as a shim.
5. **Telegram, independently.** Delete `calibration_for_subnet` and the `state_vector` block; drop the two ctx keys from `scoring_context`; replace `test_telegram_evidence_calibration.py` with one assertion that no council module imports `message_intel.calibration`. Keep `rollup`, `proof`, routes, engine status — the product feature survives; only the score path loses it.

Step 5 is deliberately last and independent: if it lands first and something downstream depended on the field, the failure is attributed to the wrong change.

### Invariants → tests

- `build_snapshot` returns exactly `len(universe)` rows at N = 24, 40, 128, 300. No truncation at any N.
- `Selection.complete` is true for `full()` on any non-empty universe — the invariant the current code cannot satisfy.
- Every dropped netuid appears in `Selection.dropped` with a reason; `sum(len(rows) + len(dropped)) == len(input)`.
- No module imports `scoring_cap`; no module outside `server.py` reads `TOP_SCORING_UNIVERSE`.
- No council module imports `server`.
- Telegram removal changes no score by more than `0.0` — assert the adjustment was already zero, don't assume it.

### What would make me scrap this

- Two independent call sites needing something other than "all" or "deadline" → the budget type is wrong, not the callers.
- The ranker parameter being passed as `None` in more than one place (i.e. ranking gets reintroduced as a default).
- `Dropped` growing a third reason before step 3 ships.
- Any caller reaching into `Selection` internals to reconstruct a count.

---

## The one number that decides whether step 3 ships alone

Removing the cap multiplies snapshot work by roughly `128 / 40 ≈ 3.2×` at `SCORE_SNAPSHOT_SCORE_WORKERS = 2`. The denominator is the production snapshot cap (`SCORE_SNAPSHOT_MAX_SUBNETS = 40`, `fly.toml:89`), not the pick cap of 24. This is a workload-count ratio, not a measured runtime. The audit's Part III has the production measurements; I did not re-derive them this pass. Before step 3 lands, the falsifier is: **plot `build_wall_seconds` and `build_cost.cpu` against N for at least two N values.** If either grows super-linearly, step 3 ships with a deadline budget and a workers bump, not alone. If it grows linearly, the cap was always compensating for the Telegram scan, and it can go without a replacement.

Either way the decision is made from the two numbers, not from the argument that the cap "felt" necessary.


---

*Nothing in this document has been applied. Steps 1–5 are proposals, ordered so that each is verifiable alone.*

---

## Part V — Calibration Window Contract (the 3,000-row problem)

*Originally `calibration-window-contract-2026-10-18.md`. Design only — nothing applied. Pin `3a65d34a`. Superseded in scope by Part VI.*

**Repository:** `cryptoreporthub/subnet-dashboard` · **Pin:** `3a65d34ac46a28395559310f21db013b4581c645`
**Date:** 2026-10-18 · **Mode:** /architect · **Status:** design only — nothing applied.

Second design pass. The first ([Scoring Universe Contract](scoring-universe-contract-2026-10-18.md)) answered *whether Telegram should cost anything on the score path*. This one answers *what the 3,000-row scan should become* — for the paths that keep it.

## Phase ledger

| Phase | State | Note |
|---|---|---|
| **A — Ground** | done | query shape, proof cost, and two clocks read at the pin |
| **B — Sketch** | done | 3 candidates, screened |
| **C — Agree** | waiting | this is the checkpoint |
| **D — Implement** | not started | |

---

## Phase A — Ground

### What the 3,000 is

    # rollup.py:1077 (_query_conviction_rows); LIMIT 3000 at 1096
    SELECT m.id, m.source, ..., a.entities_json, v.verdict, v.conviction, ...
           ps.tao_usd_price, po.price_24h, po.price_24h_recorded_at
    FROM messages m
    LEFT JOIN message_analysis a / message_verdicts v / price_snapshots ps / price_outcomes po
    WHERE m.source = 'telegram'
    ORDER BY m.id DESC LIMIT 3000

Four things are true of that query, and only one of them is the one everybody quotes:

1. **It has no time predicate.** The number 3,000 is the entire window definition — not a cache size, not a page. It is ordered by `m.id DESC`, i.e. ingestion order.
2. **It is a five-way LEFT JOIN.** Every row drags price snapshots and outcomes along whether or not the calibration needs them.
3. **It is shared.** `_conviction_rows()` also feeds `build_todays_conviction`, caller leaderboards, and receipt listings — which use *their own* windows (7d, 30d). The 3,000 is a compromise across all of them.
4. **Its consumer declares a 72h window** (`DEFAULT_CURRENT_WINDOW_HOURS = 72`) that the query knows nothing about.

### Two clocks

```
calibration_health      freshness = price_24h_recorded_at   (when the outcome was graded)
calibration_for_subnet  window    = timestamp | created_at  (when the call was made)
```

Both are legitimate; they answer different questions. But combined with `LIMIT 3000` ordered by message id, the *current* window is silently sliced by message volume: if the last 3,000 Telegram messages span less than 72 hours, the oldest in-window calls are dropped and the "current consensus" is biased toward the most recent day. If they span more than 72 hours, thousands of rows are fetched and discarded in Python. **I have not measured production Telegram volume** — that is the one number that decides which of those two cases is live, and it is a `COUNT(*)` away.

### What one row costs

    classify_call(row)
      → resolve_direction, _resolve_subnet_identity, horizon_summary (1h/4h/24h),
        magnitude_quality, ~40 field reads

    _netuids_from_row(row)
      → json.loads(entities_json) + json.loads(raw_json) + re.findall per row

and both are called **per subnet** on the scoring path. With health, per-subnet calibration and author reliability all classifying the same rows, one request can classify a row **three to four times**, and `_netuids_from_row` **once per netuid**.

### The seam

The architecture problem is not the constant. It is that **there is no type for "the Telegram evidence as of now"** — so every caller re-derives it from raw rows, with its own clock, its own filter, and its own cap. That is the same disease as the scoring universe: eight sites, one question, no single answer.

---

## Phase B — three candidates

**A. Delete it from scoring** (the first doc's step 5). Correct, and it removes N × 3,000 from the score path — but it removes *nothing* from `/api/message-intel/calibration` or `engine.telegram_calibration_status`, which keep the full scan per request. It hides the problem behind a default-off flag rather than fixing it.

**B. One immutable window object per request/batch.** Build once, share by argument.

    window = build_window(rows, now=now, since=now-72h)
    window.adjustment(netuid)     # O(1) lookup
    window.health()               # computed once, not re-derived

Every row is classified once; netuids are parsed once; the per-subnet loop disappears. No schema change, no migration.

**C. Push the window into SQL.** `WHERE m.timestamp >= ?` for a calibration-specific query, plus an index on `(source, timestamp)`. Kills the volume-bias and the wasted rows — but on its own it still leaves the per-netuid re-scan.

### Screen

| Red flag | A | B | C |
|---|---|---|---|
| One answer to "what is the evidence now" | ✗ | ✓ | ~ (query only) |
| Row classified once, not per subnet | ✗ | ✓ | ✗ |
| No silent count truncation | ✗ 3,000 survives | ~ (records excluded) | ✓ |
| Needs schema migration | ✓ no | ✓ no | ✗ yes |
| Fits existing call sites | ✓ | ✓ (signature change) | ✓ |
| Next agent can't reintroduce the scan | ✗ | ✓ | ~ |

### Synthesis

**B is the spine; C is one line inside it.** `build_window` gets its rows from a calibration-specific query that carries the 72h predicate (C), then classifies and groups each row exactly once (B). A alone is not a design, it is a subtraction — and it stays in the plan, but for product reasons, not performance ones.

---

## Contract

### Usage sketch (written first)

    # routes.py — one build per request
    window = load_window(since=now - timedelta(hours=72))
    return calibrate_payload(window)

    # calibration.py — unchanged public behaviour, new plumbing
    def calibration_health(*, window: Window) -> dict
    def calibration_for_subnet(netuid, *, window: Window) -> dict
    def calibration_config() -> dict          # the only env read

    # state_vector.py — if Telegram stays in scoring, one window per batch
    window = (market_context or {}).get("telegram_window")
    total += window.adjustment_for(sn.get("netuid"))["adjustment_points"] if window else 0.0

### Types

    # internal/message_intel/calibration_window.py  (new)

    @dataclass(frozen=True)
    class CallFact:
        row_id: int
        netuids: frozenset[int]
        author: str                      # stable_author_id, computed once
        direction: Literal["up", "down"]
        at: datetime                     # message timestamp
        status: str                      # classify_call status, computed once
        resolved: bool

    @dataclass(frozen=True)
    class Window:
        since: datetime
        now: datetime
        facts: tuple[CallFact, ...]                  # eligible + inside window
        excluded: Mapping[str, int]                  # reason -> count, full accounting
        truncated: bool                              # query hit its row cap
        source_row_count: int                        # what SQL returned, always reported

        def facts_for(self, netuid: int) -> tuple[CallFact, ...]
        def health(self) -> dict
        def adjustment_for(self, netuid: int) -> dict
        @property
        def accounted(self) -> bool                  # len(facts)+sum(excluded) == source_row_count

    def build_window(rows, *, now, since) -> Window
    def load_window(*, since, db=None) -> Window     # SQL predicate lives here, nowhere else


### Module map

| Unit | Owns | May import |
|---|---|---|
| `message_intel/calibration_window.py` **(new)** | the type, the builder, the one SQL | `proof`, `rollup` helpers (read-only) |
| `message_intel/calibration.py` | `health`, `adjustment_for`, config validation | `calibration_window` |
| `council/scoring_context.py` | passes an optional `Window` | **not** `message_intel` internals |
| `council/state_vector.py` | consumes `Window` | types only |
| `rollup._conviction_rows` | **unchanged** | — |

The last row matters: tightening `_conviction_rows`' window would silently change every leaderboard and receipt listing that shares it. The new windowed query is a *separate* function. Shared queries keep their old contract.

### Migration — five verifiable units

1. **`build_window` + tests, unwired.** Nothing calls it; production identical.
2. **Differential proof.** On a frozen fixture, for every netuid, `window.adjustment_for(n)` must equal the current `calibration_for_subnet(n, conviction_rows=...)` byte-for-byte, and `window.health()` must equal `calibration_health(conviction_rows=...)`. This test is the whole change's safety net; it lands before anything is swapped.
3. **Swap the calibration route and engine status** to `load_window`. One build per request instead of three.
4. **Change the two signatures** to take `Window`; delete the `conviction_rows:` parameters. Callers either build a window or pass none.
5. **Push the predicate into SQL** and delete `LIMIT 3000` from the calibration path only. Report `source_row_count`, `truncated`, and the min/max timestamps in the health payload.

### Invariants → tests

- **Differential equality** (unit 2) — the change is provably a no-op on scores.
- `window.accounted` is true for every fixture: rows in == facts + excluded. No silent drop, ever.
- Exactly **one** `classify_call` per row per request — assert with a counting patch.
- `adjustment_for` on a netuid absent from the window returns `adjustment_points == 0.0` and the same `withheld_reasons`.
- `truncated` is true, not false, when the query cap binds — and the health payload says so.
- No council module imports `message_intel.rollup`.

### What would make me scrap this

- A consumer needing a *different* window than 72h on the same object (→ the parameter belongs on `load_window`, not on the type).
- `excluded` growing reasons that the health payload can't explain (→ the accounting is decorative).
- `CallFact` accumulating fields only one caller uses (→ that caller should classify its own rows).
- Anyone reaching for `.facts` outside `calibration_window.py`.

---

## What this changes about the first contract

The first doc deleted Telegram from scoring because the scan was provable waste. With a window object built **once per batch**, the score path costs one pass over the window regardless of how many subnets it scores. So:

> **Deleting Telegram from scoring becomes a product decision, not a performance one.**

That is a better position to be in: the flag `TELEGRAM_EVIDENCE_CALIBRATION` can be turned on later without a cliff from N × 3,000, and the score path no longer needs to know how many subnets it holds. I'd still make step 5 of the first doc the thing we ship *last* — and only if you want the field gone.

---

*Nothing here has been applied. The one measurement I cannot make for you: Telegram messages per 72 hours in production, and whether that exceeds 3,000.*

---

## Part VI — Telegram Scope Lock (decision record)

*Originally `audit-telegram-scope-lock-2026-10-18.md`. This is the decision of record for Telegram's disposition. Pin `3a65d34a`.*

**Repository:** `cryptoreporthub/subnet-dashboard` · **Pin:** `3a65d34ac46a28395559310f21db013b4581c645`
**Decision (yours, this turn):** Telegram comes out of scoring. Not made cheap — **gone**. Telegram data stays inside Telegram surfaces (`/listener` and its own routes) and does not reach council or judges.
**Status:** agreed design, nothing applied. Supersedes *how* the 3,000 rows get handled in [Calibration Window Contract](calibration-window-contract-2026-10-18.md) for the score path.

---

## Why this is the cheaper decision

The previous two documents argued over two ways to make the scan affordable: delete the consumer, or bound the window. Your call collapses that: delete the consumer, and the scan leaves the score path entirely. What remains of the window work is an *optimization for Telegram's own pages*, not a performance gate for scoring.

Concretely, this removes:

| Currently per scoring pass | After |
|---|---|
| `_conviction_rows()` — 5-way LEFT JOIN, `LIMIT 3000`, per batch | 0 |
| `calibration_health()` over those rows, per batch | 0 |
| `classify_call` 3–4× per row on the score path | 0 |
| `_netuids_from_row` `json.loads` + regex, **per netuid** | 0 |

---

## Phase A — the bleed sites, read at the pin

There are exactly **three**, in **two** council files. Everything else is already clean: `orchestrator.py` and `daily_pick_engine.py` contain zero `message_intel`/`telegram` references, and `signal_expert.py`, `input_processor.py`, `experts/hype.py` contain none either.

**1. `internal/council/state_vector.py` — the adjustment itself** (`telegram_calibration = None` at line 1893, apply at 1907)

```python
telegram_calibration = None
try:
    from internal.message_intel.calibration import calibration_for_subnet
    conviction_rows = (market_context or {}).get("telegram_conviction_rows")
    telegram_calibration = calibration_for_subnet(sn.get("netuid") or sn.get("id"), ...)
    total = min(100.0, max(0.0, round(total + telegram_calibration["adjustment_points"], 2)))
```

The comment already concedes the design intent — *"Telegram history never changes council weights and is default-off until operators explicitly enable it."* A score path that ships a dormant mutator is a loaded gun. It goes, and the field `telegram_evidence_calibration` in the score payload (~line 1961) goes with it.

**2. `internal/council/scoring_context.py` — `enrich_scoring_market_context`**

Half of that function exists only to load Telegram for site 1:

```python
if "telegram_conviction_rows" not in ctx:
    from internal.message_intel.rollup import _conviction_rows
    ctx["telegram_conviction_rows"] = _conviction_rows()
if "telegram_calibration_health" not in ctx and ...:
    from internal.message_intel.calibration import calibration_health
```

Delete those two blocks; keep the `scenario_memory` half, which is a different concern.

**3. `internal/message_intel/engine.py:600` — `telegram_calibration_status()`**

A calibration health endpoint served from the *engine*. It stays, but as a listener-diagnostic route owned by `message_intel/routes.py`, not a council-facing surface.

---

## Phase B — delete the capability, not just the call

Deleting site 1 leaves `calibration_for_subnet()` with **no consumer** — a function whose entire public contract is *"return `adjustment_points` for a netuid."* That function is the leak. Keeping it means the next agent re-wires it in an afternoon, and the scope rule becomes folklore.

> **Rule: if nothing may apply Telegram to a score, then nothing may return a Telegram score adjustment.**

So `calibration_for_subnet`, `adjustment_points`, and `TELEGRAM_EVIDENCE_CALIBRATION` are deleted. `calibration_health()` survives as a **listener-only diagnostic** (it answers "are Telegram calls resolving at all", which `/listener` genuinely shows) — it just never returns something a score can consume.

---

## Contract

### The fence

```
internal/message_intel/**    owns Telegram data. May import council types (read-only).
internal/council/**, judge/**   must never import internal.message_intel.
server wiring            imports message_intel.routes for /listener endpoints only.
```

### Invariants → tests

1. **Import fence, mechanical.** `test_council_has_no_telegram_imports`: walk every module under `internal/council/` and `internal/council/judge/`, AST-parse it, assert no `import internal.message_intel` / `from internal.message_intel...`. This is the rule; the deletions are just the first payload.
2. **No dormant mutator.** `test_calibration_module_exposes_no_adjustment`: assert `calibration` has no attribute `calibration_for_subnet` and no `adjustment_points` key path. (Inverts the guarantee — a re-introduction fails CI.)
3. **Context carries no Telegram.** `enrich_scoring_market_context({})` returns a dict whose keys contain no `telegram_` prefix.
4. **Score payload has no Telegram key.** The score output dict has no `telegram_evidence_calibration`.
5. **Score-neutral, proven.** Replay a frozen snapshot through `score_universe` before/after: identical scores. If the prod flag is off, this must pass exactly; if it is on, the diff is the expected delta and is reviewed, not waived.

### Units (each ends verifiable)

1. **Fence test alone, red.** Land invariants 1–4 as failing tests at the current tree. They should fail on all three sites — proof the fence measures reality.
2. **Delete site 2** (`scoring_context.py` Telegram half). Invariant 3 goes green; site 1 now receives `None` for both keys — a safe intermediate where the code still runs.
3. **Delete site 1** (`state_vector.py` block + payload field). Invariant 4 green.
4. **Delete the capability** (`calibration_for_subnet`, `adjustment_points`, the env flag) and move `telegram_calibration_status` into `message_intel/routes.py`. Invariants 1–2 green.
5. **Score-neutral replay** on a frozen snapshot; then deploy.


Order matters: the fence lands **first and red**, so every subsequent unit has a gate that was already failing. This is the "prove the check catches a real past mistake" discipline — the past mistake is these exact three sites.

### Pre-flight, before anything ships

```
flyctl secrets list -a subnet-dashboard | grep TELEGRAM_EVIDENCE_CALIBRATION
```

Default for the flag is off, and the earlier read confirmed it is never applied. **If that is not true in production**, this change moves live scores and needs a reviewed before/after diff instead of a neutral replay. One command decides which world we are in.

---

## What falls out of the other two docs

- **The 3,000-row scan leaves the score path entirely** — not bounded, removed. The two `LIMIT 3000` sites that remain (`_conviction_rows`, `list_telegram_caller_activity`) now serve only Telegram's own surfaces.
- **The `Window` type in the calibration-window doc is now optional polish**, scoped to `/listener` and `/api/message-intel/*`. Worth doing later for the 72h-vs-message-id-bias problem; no longer on the critical path, and no longer a reason to touch scoring.
- **The caps / 3.2× snapshot question is fully decoupled.** Telegram removal does not change it, and it should not ride along in this change.

---

*Nothing applied. Pin is `3a65d34`; the three sites above are read verbatim from it.*

---

## Part VII — Telegram Bleed Audit (verified at both SHAs, with live probes)

*Originally `telegram-bleed-audit-2026-10-18.md`. Verification layer for Parts II–VI: raw-file line map at PIN and PROD, today's production reads, and the corrected fix order.*

**Scope:** research, verification, and named fixes only. No file edited, no branch cut, no job dispatched, no production state changed.
**Prepared:** 2026-10-18, 19:57–20:12 PDT (2026-10-19 02:57–03:12Z).
**Audience:** Claude, for review and assessment. Everything needed to assess is in this file.

---

## 1. SHA manifest — read this first

Line numbers drift between commits and between views of a file. Every claim below names its SHA.

| Role | SHA | Date (UTC) | Commit subject | How verified |
|---|---|---|---|---|
| **PIN** — audit pin | `3a65d34ac46a28395559310f21db013b4581c645` | 2026-10-18T00:59:45Z | `feat(snapshot): per-build cost counters (#1458, refs #1372)` | GitHub commit API |
| **PROD** — live deployment | `357980b43f374ca9bf109380a7229afab0c77643` | 2026-10-17T16:00:40Z | `docs: deploy vehicle for main 387ecfdf (#1439 reserve hex)` | `/version` on subnet-dashboard.fly.dev |
| **HOIST** — adds `scoring_context.py` | `49faea952fa6fdad5a3f5e7990720425bb99e1cf` | 2026-10-17T22:09:17Z | `feat(scoring): profile-driven hoist, parallel snapshot scoring, snapshot API reads` | main commit list |
| **PROFILE** — the gap-analysis doc | `ef234c95aa227c21318dd7292ad8228003495589` | 2026-10-17T16:04:31Z | `docs: deploy vehicle 387ecfdf (#1439 reserve hex)` | main commit list |

**PROD is 6 commits behind PIN.** Commits between them, oldest first:

1. `ef234c95` — docs: deploy vehicle 387ecfdf
2. `61d49f3f` — feat(scoring): read top-picks and weighed shortlist from score snapshot
3. `49faea95` — feat(scoring): profile-driven hoist, parallel snapshot scoring ← **adds `internal/council/scoring_context.py`**
4. `bb4ce004` — feat(snapshot): per-build cost counters for conviction queries, RPC attempts
5. `cd0c7b94` — feat(scoring): profile hoist, parallel snapshot build, request-path snapshot reads
6. `3a65d34a` — feat(snapshot): per-build cost counters (#1458)

**Consequence for review:** the code being audited is *ahead of what is running*. Item 4 — instrumentation that would count conviction queries per build — **exists on main and is not deployed**, so the bleed cannot yet be measured from production.

### Line-number convention

All line numbers in §4 are **raw-file lines** (LF, whole file, fetched from `raw.githubusercontent.com` at the named SHA). Earlier drafts in this thread quoted *payload-relative* numbers from a markdown-converted view, which sit ~2 lines higher and are quoted for the blocks containing them. Do not mix the two. §10 records every correction.

---

## 2. Probe log — what was actually read live

All read-only GETs against `https://subnet-dashboard.fly.dev`, 2026-10-18 19:57–20:05 PDT.

| # | Endpoint | Result | Time (PDT) |
|---|---|---|---|
| P1 | `/version` | `{"version":"357980b43f374ca9bf109380a7229afab0c77643","sentry_release":"357980b43f374ca9bf109380a7229afab0c77643","python":"3.12.15"}` | 20:02 |
| P2 | `/health` | `OK` (200) | 20:02 |
| P3 | `/api/message-intel/calibration` | see verbatim below | 20:04 |
| P4 | `/api/council` | 200, keys `status, subnets, judges, meta` — no `telegram_evidence_calibration` present in the council aggregator payload returned | 20:04 |
| P5 | `/api/top-picks` | `{"hour_picks":[],"day_picks":[],"status":"timeout"}` | 20:05 |

**P3 verbatim (prod, 357980b4):**

`{"status":"success","version":"telegram-outcomes-v1","enabled":false,"active":false,
 "withheld_reasons":["disabled_by_environment","historical_quality_below_threshold"],
 "source":"verified_telegram_24h_outcomes","source_sample_size":12,
 "verified_resolved_count":21,"hits":2,"hit_rate":0.1667,
 "freshness":{"max_age_days":30,"latest_resolved_at":"2026-10-17T12:03:33.649782+00:00","fresh_sample_size":12},
 "thresholds":{"min_samples":10,"min_hit_rate":0.55,"max_age_days":30},"factor":1.0}`

**Internal coherence check (this is why P3 is trustworthy as a live read, not a cached blob):** `calibration_health` appends `insufficient_verified_samples` only when `len(fresh) < min_samples` (PIN `calibration.py:210`). The payload omits that reason and reports `fresh_sample_size: 12` against `min_samples: 10`. The reasons list matches the arithmetic that produces it, so the fields are mutually consistent.

**P5 is an observation, not a finding.** `/api/top-picks` returned `status: timeout` with empty arrays at probe time. Flagged because it is a live symptom worth someone's attention; **not** attributed here to the Telegram path, and not evidence either way.

---

## 3. Verdict

1. **The coupling is live; only its effect is muted.** Production has the calibration flag **off** (P3, `enabled:false`). So `adjustment_points` is `0.0` and **S2 has never moved a published score.** But the scan in `calibration_health` happens *before* the flag is consulted, so the read cost is still paid on every scoring batch.
2. **The flag is not the reason to leave it alone.** With the flag off, `hit_rate` is `0.1667` against a `0.55` floor — even if someone flips the switch, the adjustment stays withheld on quality. There is no configuration in which this code earns its cost today.
3. **Ordering matters and the obvious order is wrong.** Removing the hoist (Fix A) *before* the consumer (Fix B) makes production slower, not faster. Proof in §7.

---

## 4. The three sites — dual-SHA line map

| Site | File | PIN `3a65d34a` | PROD `357980b4` | What it is |
|---|---|---|---|---|
| **S1** | `internal/council/scoring_context.py` | **lines 17–32** (fn 8–40) | **file does not exist** (404) | Hoist: `_conviction_rows()` + `calibration_health()` into `market_context` |
| **S2** | `internal/council/state_vector.py` | **lines 1893–1912** | **lines 1893–1909** | `calibration_for_subnet` call (1900 both) + score mutation (1907 PIN / 1904 PROD) |
| **S3** | `internal/council/state_vector.py` | **line 1960** | **line 1957** | `"telegram_evidence_calibration"` in the score payload |

**S2 is the only site that can move a number. S3 is the one that makes Telegram appear in a council verdict even when it contributed nothing. S1 is the cost.**

### S1 — PIN, `scoring_context.py` 17–32

`17|    if "telegram_conviction_rows" not in ctx:
18|        try:
19|            from internal.message_intel.rollup import _conviction_rows
20|
21|            ctx["telegram_conviction_rows"] = _conviction_rows()
22|        except Exception:
23|            ctx["telegram_conviction_rows"] = None
24|    if "telegram_calibration_health" not in ctx and ctx.get("telegram_conviction_rows") is not None:
25|        try:
26|            from internal.message_intel.calibration import calibration_health
27|
28|            ctx["telegram_calibration_health"] = calibration_health(
29|                conviction_rows=ctx["telegram_conviction_rows"]
30|            )
31|        except Exception:
32|            ctx["telegram_calibration_health"] = None`
`scenario_memory_scenarios` (lines 33–39) is the only other enrichment and is **unrelated** — Fix A must leave it standing.

Callers at PIN (both verified by fetch): `internal/council/daily_pick.py:120` and `internal/council/score_cache.py:49`.

### S2 — PIN, `state_vector.py` 1893–1912

`1893|    telegram_calibration = None
1894|    try:
1895|        # Lazy, read-only boundary: Telegram history never changes council weights
1896|        # and is default-off until operators explicitly enable it.
1897|        from internal.message_intel.calibration import calibration_for_subnet
1898|
1899|        conviction_rows = (market_context or {}).get("telegram_conviction_rows")
1900|        telegram_calibration = calibration_for_subnet(
1901|            sn.get("netuid") or sn.get("id"),
1902|            conviction_rows=conviction_rows,
1903|            calibration_health_snapshot=(market_context or {}).get(
1904|                "telegram_calibration_health"
1905|            ),
1906|        )
1907|        total = min(100.0, max(0.0, round(total + telegram_calibration["adjustment_points"], 2)))
1908|    except Exception:
1909|        telegram_calibration = {
1910|            "active": False, "applied": False, "adjustment_points": 0.0,

1911|            "withheld_reasons": ["calibration_unavailable"],
1912|        }`

### S2 — PROD, `state_vector.py` 1893–1909

Identical except **the `calibration_health_snapshot=` argument is absent** and the mutation sits at line 1904:

`1899|        conviction_rows = (market_context or {}).get("telegram_conviction_rows")
1900|        telegram_calibration = calibration_for_subnet(
1901|            sn.get("netuid") or sn.get("id"),
1902|            conviction_rows=conviction_rows,
1903|        )
1904|        total = min(100.0, max(0.0, round(total + telegram_calibration["adjustment_points"], 2)))`

On PROD, nothing populates `telegram_conviction_rows` — `scoring_context.py` does not exist there — so `conviction_rows` is always `None`, and `calibration_for_subnet` falls through to a fresh DB read **per subnet** (`calibration.py:247`), then recomputes health because the snapshot is also `None`.

### S3 — payload field

PIN `1960|        "telegram_evidence_calibration": telegram_calibration,` · PROD `1957|        "telegram_evidence_calibration": telegram_calibration,`

Exact string appears **once** per zone; there is no second consumer. Repo-wide search for `calibration_for_subnet(` returns exactly three files: `internal/message_intel/calibration.py` (definition), `internal/council/state_vector.py` (the single call site), `tests/test_telegram_evidence_calibration.py` (test). **The judges path is clean** — `internal/judges/subnet_judges.py` contains no Telegram or calibration reference at all, so `score_all_subnets` → `score_subnet` is not a fourth bleed site.

---

## 5. Why the read cost is paid at all — the ordering bug

In `calibration.py` (identical structure on PIN):

`188| def calibration_health(
...
194|     rows = conviction_rows if conviction_rows is not None else _conviction_rows(db)
195|     receipts = _resolved_receipts(rows, now)
196|     scored = [r for r in receipts if r["_proof"]["status"] in {"hit", "miss"}]
...
202|     reasons: List[str] = []
203|     if not cfg["enabled"]:
204|         reasons.append("disabled_by_environment")`

**Line 194 reads the rows; line 203 is the first time the flag is consulted.** The flag gates the arithmetic, not the work. Same shape in `calibration_for_subnet`: rows load at line 247, `applied` is computed at line 283.

`_conviction_rows` is `internal/message_intel/rollup.py:1068`, with **`LIMIT 3000`** at line 1096.

Default thresholds (PIN `calibration.py:22-26`): `min_samples=10`, `min_hit_rate=0.55`, `max_age_days=30`, `max_adjustment_points=2.0`. All env-overridable; none overridden in `fly.toml`.

---

## 6. Cost model — figures, with their provenance

These numbers are **not mine**. They come from a repo doc at PIN, `docs/agent-friendly/scoring-caps-profile.md` — a separate agent's profile of the production/local gap, pinned to `ef234c95` and a prod build at release v2391.

| Model | Math | Wall for 40 names |
|---|---|---|
| Local harness, `_conviction_rows` mocked at 50 ms, no hoist | 40 × 52 ms | 2.06 s (0.052 s/name) |
| Documented extreme, 805 ms per `_conviction_rows` | 40 × 0.805 s | 32.2 s |
| **Observed prod snapshot build** | 57.7 s ÷ 40 | **1.44 s/name** |

That doc's conclusion: if prod SQLite makes `_conviction_rows` ~0.8–1.0 s, **missing hoist alone accounts for ~32–40 s of the 57.7 s build (~55–70%)**; the remainder is attributed to pump-ladder load, soul_map/weights, GIL-bound Python, a **serial** scoring loop, shared RPC cooldown, and shared-CPU-2x throttling.

**Two caveats a reviewer should hold onto:**

- The 805 ms/name figure is a *documented extreme*, not a measurement of the current deployment. The doc says so itself (line 20: "Mechanism confirmed locally — **not** deployed on prod").
- **The measurements disagree.** A separate record in this thread put the saving from removing the scan at **"about six seconds"**, not 32–40 s. Both are recorded above. They are not reconciled here, and one of them is measuring a different scope (per-pick vs per-full-universe-build, most likely). **Do not quote a single number until that is settled.**

Note the doc's own observation that `/version` and `/metrics` were timing out while it was written (2026-10-17 ~21:50Z). Today both `/version` (P1) and `/health` (P2) answered immediately — the endpoint condition has changed since that doc, even though the code condition has not.

---

## 7. Ordering hazard — Fix A alone makes production worse

This is the finding that changes the plan, so it gets its own section.

`scoring_context.py` exists **on PIN and not on PROD**. So today, prod pays a per-subnet read. The hoist is a *containment patch for a dead feature*, not a bleed site in the sense of corrupting anything.

If Fix A is applied to a tree that still contains S2:

1. `market_context` no longer carries `telegram_conviction_rows` → S2's `conviction_rows` becomes `None` (line 1899).
2. `calibration_for_subnet` sees `None` and calls `_conviction_rows(db)` itself (`calibration.py:247`).

3. `calibration_health_snapshot` also becomes `None`, so `calibration_health` is recomputed per call.

**Net effect: one 3000-row read and one full health recompute per subnet, where the hoist had just made it one per batch.** A alone is a regression. It only becomes a pure win after B removes the consumer.

**Therefore the order is B → C → (A + E).**

---

## 8. Proposed fixes

### Fix B — drop the adjustment (closes S2)
Delete PIN `state_vector.py` **1893–1912**. `total` keeps the value it had at lines 1891–1892 (`weighted + value_boost + flow_boost + size_tilt...`). Nothing downstream recomputes it: the next writer is `pump_overlay` at 1918–1928, then `recovery_risk_adjustment` at 1934–1940, both independent of this block.

**Provably score-neutral today** because `adjustment_points` is `0.0` under `enabled:false`. This is why B goes first — it is the one change that cannot move a published number, and it is what makes A safe.

### Fix C — drop the payload field (closes S3)
Delete PIN line **1960**. One occurrence. Verify no consumer of `telegram_evidence_calibration` in templates/JS before merge — the repo-wide string search returns the field only in this file at PIN, but a client-side reader in `static/` would not show up in a Python-only search.

### Fix A — sever the hoist (closes S1)
Delete PIN `scoring_context.py` **17–32**, leaving `enrich_scoring_market_context` with only the scenario_memory block (33–39). **Only valid after B.**

### Fix E — retire the hoist test
`tests/test_scoring_context_hoist.py` (34 lines at PIN) asserts `_conviction_rows` is called once per batch.

**It is weaker than it looks, and that matters:** the test builds `ctx`, calls `score_subnet_for_day(sn, ctx)` twice, and then asserts `calls["n"] == 1`. **That assertion passes whether or not S2 still exists** — delete the consumer and the count stays at 1. So the test does not protect the coupling; it only guards the hoist. After B, it is green and meaningless, quietly keeping dead code alive. That is the argument for A and E landing together.

### Fix D — owner-side disposition (separate decision)
`internal/message_intel/calibration.py` and `rollup.py` either stay alive for Telegram's own screens or `calibration_for_subnet` is deleted outright. Council no longer imports either after A+B+C, so this is a Telegram-ownership call, not an isolation one. Out of scope for this packet.

### Merge shape

| Order | Fix | Score risk | Cost effect |
|---|---|---|---|
| 1 | **B** | none (adjustment is 0.0) | none |
| 2 | **C** | none (payload field) | none |
| 3 | **A + E** | none (consumer gone) | one batch read instead of none-of-it |
| later | **D** | n/a | n/a |

B and C are in the same function and should land as one commit. A and E must be together and must be after B.

---

## 9. Invariants — the fence that should land red first

Proposed as `tests/test_council_telegram_fence.py`, four tests, all failing against PIN. The red is the deliverable: it proves the fence detects these three sites, not a category of thing that never happens.

1. `test_council_has_no_telegram_imports` — walk every module under `internal/council/` (including `judge/`, `experts/`, `signals/`), AST-parse, assert no `import internal.message_intel`. Fails at PIN on `state_vector.py:1897` and `scoring_context.py:19,26`.
2. `test_telegram_calibration_has_no_score_consumer` — assert `internal.message_intel.calibration` exposes no `calibration_for_subnet` and nothing returning `adjustment_points`. Inverts the guarantee so re-introduction breaks CI.
3. `test_scoring_context_carries_no_telegram` — `enrich_scoring_market_context({})` has no `telegram_`-prefixed key. Fails on `telegram_conviction_rows` / `telegram_calibration_health`.
4. `test_score_payload_has_no_telegram_field` — score output dict has no `telegram_evidence_calibration`. Fails at PIN line 1960.

Two constraints: the module walk must **skip nothing by name** (an exempted `judge/` makes the fence decorative), and invariant 2 must assert on attributes, not grep. Tests should import module objects and AST, not run live scoring — otherwise they pull SQLite before doing any work.

---

## 10. Correction ledger

Every claim in this thread that later evidence changed, so a reviewer can see what moved.

**Moved to Part X.2.** It is provenance, not guidance — the current statement of each of these seven items is in the body.

---


## 11. Cross-references (and a label collision to watch)

- `docs/agent-friendly/scoring-caps-profile.md` at PIN — the prod-vs-local gap analysis quoted in §6. Pin `ef234c95`, prod release v2391. Its hoist conclusion ("not deployed on prod") **still holds at 357980b4**, re-verified today by the 404.
- A **separate** packet from earlier today, `tier2-instrumentation-audit.md`, proposes its own fixes **A–D** about three-state gauges (`-1` = unknown), guard counters, `build_cost` dual-mode, and drift tests. **Those letters are not this packet's letters.** This packet: A–E = Telegram bleed. That packet: A–D = instrumentation truth. If both are in play, rename one set before anyone writes a PR.
- A live observation from that packet worth carrying forward: the fix that would *measure* this bleed — per-build cost counters for conviction queries — is commit `bb4ce004`, on main, **not deployed**.

---

## 12. What cannot be verified from here

1. **Fly secrets.** `enabled:false` is observed at the app layer. Whether `TELEGRAM_EVIDENCE_CALIBRATION` is set in the Fly environment, and whether it has ever been set, cannot be read without Fly-side access. The honest phrasing is "off as of 2026-10-18," not "never enabled."
2. **True per-call cost on the current deployment.** The 805 ms figure is a documented extreme at an older commit. `bb4ce004`'s counters are not deployed, so no live measurement exists.
3. **Client-side consumers** of `telegram_evidence_calibration`. Only the Python tree was searched.
4. **Why `/api/top-picks` returned `status: timeout` at 20:05 PDT.** Recorded, not explained.

---

## 13. Reproduction

```bash
curl -s https://subnet-dashboard.fly.dev/version
curl -s https://subnet-dashboard.fly.dev/api/message-intel/calibration

P=3a65d34ac46a28395559310f21db013b4581c645
for f in internal/council/scoring_context.py internal/council/state_vector.py \
         internal/message_intel/calibration.py internal/message_intel/rollup.py; do
  curl -s "https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/$P/$f"
done

# the prod-side 404 that proves the hoist is not deployed:
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/357980b43f374ca9bf109380a7229afab0c77643/internal/council/scoring_context.py"
```

---

**Status:** research and naming only. Nothing committed. Nothing deployed. Every claim above names its SHA or its probe.

---

## Part VIII — Reconciliation ledger

Eight documents were produced today, in an order that caused them to argue. This part rules on each disagreement. Nothing here changes a document's evidence; it decides which instruction a reviewer should follow.

### VIII.1 — Line numbers: three schemes are in circulation

Every Telegram line number quoted today was correct **relative to its own extraction**. Only one is correct relative to the file on disk. Authoritative, re-derived from raw bytes at each SHA:

| Site | PIN `3a65d34a` | PROD `357980b4` | Note |
|---|---|---|---|
| **S2** — calibration block | **1893–1912** | **1893–1909** | PIN adds the `calibration_health_snapshot=` argument (1903–1905) and pushes the exception dict down 3 lines |
| S2 call to `calibration_for_subnet` | **1900** | **1900** | same |
| S2 score mutation | **1907** | **1904** | `total = min(100.0, max(0.0, round(total + ...)))` |
| **S3** — payload field | **1960** | **1957** | `"telegram_evidence_calibration"` |
| **S1** — hoist | `scoring_context.py` **17–32** (fn 8–40) | **file absent (404)** | two blocks; scenario_memory at 33–39 is unrelated |

**Retired numbers, and where each came from:** `1898–1917 / 1898–1914 / 1965 / 1962` (Parts VI–VIII, all +5 from a five-line extraction header) · `1894/1910` (Part VI, own-line offsets) · `1897–1913` (Part II R7, payload-relative) · `1943` (Part IV Phase A — **that line does not exist**; it was an estimate, and the call is at 1900) · `1961` (Part VI, payload-relative). Part II's blanket "subtract 5" rule is already applied inside Part II — **do not apply it a second time anywhere else.**

### VIII.2 — Fix order: Part VI and Part VII disagree, and the difference is cost, not correctness

| | Part VI (scope lock) | Part VII (bleed audit) |
|---|---|---|
| Step 1 | Fence lands **red** | — |
| Step 2 | Delete **site 2** (`scoring_context.py`) | **B** — delete S2 (`state_vector.py`) |
| Step 3 | Delete **site 1** (`state_vector.py` + payload) | **C** — delete S3 payload field |
| Step 4 | Delete the capability + move status route | **A + E** — sever hoist, retire hoist test |
| Step 5 | Score-neutral replay, then deploy | capability delete, replay |

Both are **score-neutral in either order** — the adjustment is `0.0` under `enabled:false`. They differ in latency. Part VI's step 2 removes the hoist first; with S2 still present, `conviction_rows` becomes `None`, and `calibration_for_subnet` falls through to `calibration.py:247` → `_conviction_rows(db)` **per subnet**, plus a health recompute per call. Part VI calls that intermediate "safe", and it is — for scores. It is also a regression in cost that Part VI does not mention.

**Ruling: take Part VI's constraint (fence red first) and Part VII's order.** Fence → B → C → A+E → capability delete → replay. The hoist can only be removed once nothing consumes what it hoists; that is the one sequencing fact both parts agree on in substance and disagree on in order.

### VIII.3 — Does the Telegram status surface survive?

| Part | Says |
|---|---|
| **I**, change 6 | Delete `calibration.py`, `engine.telegram_calibration_status`, `routes.api_message_intel_calibration`, and the test |
| **VI**, Phase B | Keep `calibration_health()` as a **listener-only diagnostic**; delete only `calibration_for_subnet`, `adjustment_points`, and the env flag |
| **V** | The `Window` type is now "optional polish, scoped to `/listener` and `/api/message-intel/*`" |

**Ruling: VI and V stand; I's change 6 is superseded on this point.** Deleting the *capability to emit a score adjustment* is the decision. Deleting the *diagnostic that says whether Telegram calls are resolving* removes a surface `/listener` genuinely uses, and nothing in the evidence asks for that. **Flag for the owner:** if the intent was a clean swing of the axe rather than a fence, say so and I's change 6 governs instead. This is the one place where two documents give opposite instructions with equal confidence.

### VIII.4 — Which universe size is real

Four numbers circulate; all four are real, at different doors.

| Door | Effective limit | Source |
|---|---|---|
| `server.py` homepage shell (1066) | **20** | `min(24, TOP=20)` |
| `server.py` hourly pick (3363) | **20** | `min(24, TOP=20)` |
| `pick_scheduler._load_capped_subnets` | **20** | `min(24, server.TOP)` |
| `daily_pick_engine._subnets_for_pick_creation` | **24** | local `TOP` default **40** |
| `pick_selection_audit._scheduler_cap_limit` | **24** | local `TOP` default **40** |
| snapshot build `_snapshot_subnet_cap()` | **0** (env unset) → **40** in worker mode | two defaults in one function |

**Ruling: the scheduler universe is 20; the daily pick's regen path is 24; the snapshot's is 0-or-40.** Part II R4 ("20, not 40") is the headline correction and it holds. The claim that the pick universe is "24" describes only the regen path and is wrong for the scheduler. Part IV's finding — *four* defaults, not two — is the fuller statement and does not contradict R4; it explains it.

### VIII.5 — The cost numbers do not reconcile, and the packet must not pretend they do

| Figure | Where | Scope | Status |
|---|---|---|---|
| ≈127 × 3,000 ≈ **380k `classify_call` calls/cycle** | Part I, evidence table | full universe, row loop | arithmetic, not measured |
| **2.06 s / 40 names** at 50 ms mocked read | Part III §7 (local harness) | no hoist, sandbox | measured locally |
| **32.2 s / 40 names** at 805 ms | Part III §7, via `scoring-caps-profile.md` | prod-shaped, extreme | documented extreme, not current |
| **57.7 s observed build** = 1.44 s/name | Part III §7 (prod) | actual | measured |
| "≈**6 s**" total saving from removing the scan | an earlier record today | per-pick, likely | **unreconciled** |
| **3.2×** build multiplier (128/40) from removing the cap | Part IV | snapshot build | arithmetic |

**Ruling: quote no single number.** The 57.7 s and 1.44 s/name are measurements; the rest are estimates at different scopes, and the ~6 s figure contradicts 32–40 s by an order of magnitude. The command that settles it is `bb4ce004`'s counters — **on main, not deployed** (VIII.7).

### VIII.6 — The flag question: closed

Parts II (§6), IV (pre-flight) and VI (pre-flight) all leave open "is `TELEGRAM_EVIDENCE_CALIBRATION` set in production?", and treat the answer as deciding whether the change moves live scores.

**Ruling: closed, and the world is the neutral one.** Today's live read of `/api/message-intel/calibration` on PROD `357980b4` returns `enabled:false`, `active:false`, `withheld_reasons:["disabled_by_environment","historical_quality_below_threshold"]`, `source_sample_size:12`, `hit_rate:0.1667`, thresholds `min_samples:10, min_hit_rate:0.55`. The score-neutral replay in Part VI unit 5 must therefore pass **exactly** — any delta is a bug, not a reviewed change.

Two caveats the ruling keeps: the payload proves the state **today**, not its history, and it does not prove the secret is absent from the Fly environment (only that the code reads it as off). And even if someone flips the flag, `hit_rate 0.1667 < 0.55` keeps the adjustment withheld on quality — there is no configuration in which this code pays its cost today.

### VIII.7 — The instrumentation for this very bleed is undeployed

Part III's fixes (three-state gauges, guard counters, `build_cost` dual-mode, drift tests) and Part VII's need for a measurement point meet at one commit: `bb4ce004` "per-build cost counters for conviction queries, RPC attempts". It is on main, between PIN and PROD in the wrong direction — **it exists on main and is not in production**, because PROD is six commits behind.

**Ruling:** any plan that says "measure first, then remove" is blocked until a deploy. The alternative — remove on the strength of a provable zero adjustment — is available today and does not require the measurement. That is why Part VII's order is shippable and Part III's measurement work is not a prerequisite.

### VIII.8 — What each document still owns

| Document | Still authoritative for | Superseded on |
|---|---|---|
| **I** — Spec | Locked decisions; the change list as originally scoped | Telegram status-surface deletion (→ VIII.3) |
| **II** — Cap audit Rev 3 | Receipts R1–R12, verdict audit H1–H10, gaps, fence | Its "subtract 5" rule is local to Rev 3's own citations |
| **III** — Tier 2 | Instrumentation map, prod measurements, fixes A–D (**note: a different A–D from VII's**) | Nothing; measurement prerequisites blocked per VIII.7 |
| **IV** — Scoring universe | Eight sites, four defaults, the `Selection`/`ScoringBudget` contract, migration order | Its `state_vector.py:1943` citation — no such line; the call is at 1900 (→ VIII.1) |
| **V** — Calibration window | The two clocks, the row-cap bias, the `Window` type | Its scope: demoted to listener-only by VI |
| **VI** — Scope lock | **The decision**: Telegram out of scoring, capability deleted, fence red first | Fix order (→ VIII.2); status-surface deletion (→ VIII.3) |
| **VII** — Bleed audit | Dual-SHA line map, live probes, corrected ordering, the hoist-test weakness | Nothing |

### VIII.9 — The letter collision

Two independent fix sets are labelled **A–D**:

- **Part III:** A = three-state gauges · B = guard counters · C = `build_cost` dual-mode · D = drift tests
- **Part VII:** A = sever hoist · B = drop adjustment · C = drop payload field · D = owner-side disposition · E = retire hoist test

**Ruling: keep both, never bare.** Write "Fix III-A" and "Fix VII-A" in any PR description or review comment. They are unrelated code.

---

## Part IX — What is still unverified

Ordered by what would change a decision fastest.


| # | Question | Why it matters | How to settle it |
|---|---|---|---|
| 1 | Telegram messages per 72 h in production — above or below 3,000? | Decides whether `LIMIT 3000` biases the current window or merely over-fetches (Part V, Phase A) | one `COUNT(*)` on `messages` where `source='telegram'` and `timestamp >= now-72h` |
| 2 | Real `_conviction_rows` cost per call on PROD | Decides whether the hoist is worth its complexity or the scan is the whole story (VIII.5) | deploy `bb4ce004`; read `build_cost` conviction counters |
| 3 | Was `TELEGRAM_EVIDENCE_CALIBRATION` ever set in the Fly env? | The payload proves "off now", not "never on" | `flyctl secrets list -a subnet-dashboard` — history is not retained, so this may be unanswerable |
| 4 | Does anything client-side read `telegram_evidence_calibration`? | Fix VII-C deletes the field | grep `static/` and templates; Python-only search already returned one occurrence |
| 5 | Does `PICK_SCHEDULER_UNIVERSE_CAP` declare a module default? | Part IV lists it as read-not-verified | read the declaration in `pick_scheduler.py` |
| 6 | Why did `/api/top-picks` return `status: timeout` at 20:05 PDT? | Live symptom, unrelated to Telegram | run logs at that timestamp |
| 7 | Does the 3.2× multiplier hold? | Decides whether Part IV step 3 ships alone or with a deadline budget | plot `build_wall_seconds` and `build_cost.cpu` against N for two values of N |

---

*Compiled 2026-10-18. Ten parts, one file. Nothing applied.*

---

## Part X — Provenance appendix

Every claim in this packet that later evidence changed, and every number that was in circulation and is not any more. Moved here so the body of the packet states only what is currently true, and so a reviewer never has to decide whether a row is a finding or a correction to one.

**How to read this part.** Nothing here is guidance. If a line below contradicts something in Parts I–IX, Parts I–IX win, because those are the current statements. These tables exist so the audit can be audited — not so it can be re-derived.

### X.1 — Part III: audit ledger (was III §11)

Kept so the packet does not depend on the conversation that produced it.

| # | Claim I made | Where | Verdict | Evidence |
|---|---|---|---|---|
| 1 | Tier 2 adds "~1% overhead" | §1 | **Withdrawn — unfounded** | Never measured; not derivable from any metric |
| 2 | `build_cost` can see Tier 2 | §5 | **Confirmed defect** | `build_cost.py` `record()` no-ops when `_active is None`; zero `message_intel` metrics in prod |
| 3 | `/api/message-intel/status` is a hot path | §3 | **Refuted — my error** | 1 request / 8,040 s uptime |
| 4 | Most rows fail the `conviction >= 60` gate | §2 | **Refuted — my error** | 1,817 of 5,812 = 31.3% pass |
| 5 | A TTL cache on the status endpoint is needed | §3 | **Dropped** | 15.5 ms observed; traffic absent |
| 6 | Scheduler gauges are trustworthy | §4 | **Refuted** | `running` and `job_count` read `0` while readiness builds at 18.6 s age (2026-10-21); resolver `last_ok` reads `1` |
| 7 | The patch might never be scraped (multiprocess) | §5.4 | **Reopened 2026-10-21 — worker not scraped** | `scripts/fly_web_entrypoint.sh:34` (pin; line 90 at `4560c10d`) starts the worker as a second process; no multiprocess dir |
| 8 | The hourly horizon metric looks broken | — | **Retracted — by design** | `snapshot_coverage.py:464-467` |
| 9 | The repo needs a full overhaul | §9 | **Rejected** | 61.7 s build vs 8 ms publish (unverified, §7.3); the defect is truth, not structure |

Three of these nine were my own errors, all of the same kind: **I trusted a comment or an inference where a measurement was available.** That is the same failure mode as the gauges. It is worth keeping in the packet, because the packet's conclusion — that this codebase needs a truth layer, not a rewrite — is a claim about a class of error that I made three times while auditing it.

### X.2 — Part VII: correction ledger (was VII §10)

Every claim that later evidence changed, so a reviewer can see what moved.

| # | Earlier claim | Now | Evidence |
|---|---|---|---|
| 1 | "Production flag state is unverified — it decides whether S2 has been moving published scores." | **Resolved: flag off.** S2 has never moved a score. | P3 live read + `fly.toml` [env] at PIN |
| 2 | "S1 at `scoring_context.py:22–37`; S2 at 1898–1918; S3 at 1965." | Raw file offsets: **S1 17–32**, **S2 1893–1912** (prod 1893–1909), **S3 1960** (prod 1957). | §4 + VIII.1; every earlier variant came from a header-shifted extraction |
| 3 | "The bleed is a scoring-correctness problem." | It is a **latency** problem. Only the arithmetic is muted; the coupling is live. | §5 ordering: rows read before flag check |
| 4 | "Fix A can land independently and is the one that removes the cost." | **A must land after B.** A alone regresses prod to per-subnet reads. | §7 |
| 5 | "Removal saves ~32–40 s per build." | **Unreconciled.** Another record says ~6 s. Do not quote either yet. | §6 |
| 6 | Implied: the code under audit is what is running. | **Prod is 6 commits behind PIN** and does not contain `scoring_context.py` at all. | `/version` + 404 on raw fetch at PROD |
| 7 | "The hoist test protects the coupling." | It cannot fail if S2 is deleted; it only guards the hoist. | §8 Fix E |

Things earlier drafts stated that are **still true** and re-verified: the flag gates arithmetic not coupling; the flag default is off in code (`calibration.py:164`); `adjustment_points` is bounded at 2.0 points; `daily_pick_engine.py`, `score_snapshots.py`, `server.py` contain no `scoring_context` reference at PIN.

### X.3 — Line numbers that were in circulation and are not any more

Every one of these was correct relative to its own extraction and wrong relative to the file. **VIII.1 is the only authoritative map.**

| Retired | Scheme | Source |
|---|---|---|
| `1898–1917` / `1898–1914` / `1965` / `1962` | file offset **+5** | a five-line header on a downloaded copy; the header rule at the top of this file exists because of it |
| `1894` / `1910` | own-line offsets | Part VI |
| `1897–1913` | payload-relative | Part II R7 |
| `1943` | **no such line** | Part IV Phase A — an estimate, never a read. The call is at 1900 |
| `1961` | payload-relative | Part VI |
| `22–37` (S1) | header-shifted | the hoist is at `scoring_context.py` 17–32, function 8–40 |
