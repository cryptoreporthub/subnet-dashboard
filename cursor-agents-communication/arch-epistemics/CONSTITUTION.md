# Campaign Constitution — Architecture Epistemics

**schema_version:** `1`  
**status:** **FROZEN** (Joshua Go 2026-09-19T10:45Z) — do not edit without a new freeze  
**campaign_pin.repo_sha:** `c9449d6490231373748f19f299ed19d423a1c971`  
**campaign_pin.deploy_sha:** `NOT_OBSERVABLE`  
**campaign_pin.runtime_ref:** `NOT_OBSERVABLE`

## Non-negotiables

1. No claim without `SHA:path:line` **and** literal bytes read (or explicit `NOT_OBSERVABLE`).
2. Filenames / docstrings / PR titles are not behavior; call sites are.
3. Discovery ≠ authorization: no fixes, PRs, deploys, or live probes without Joshua's separate Go.
4. Tier A only after Joshua (or named non-author) spot-checks the exact citation.
5. Grok seats never call Ditto. Memory enters only via Joshua → Ledger as Tier B (`evidence_class: memory`).
6. Mission Control is the only router. Seats communicate through queue/bundle **files**, not prose DMs.
7. Answering from model memory without a recorded `fetch_method` is forbidden.

## Pin protocol

- One campaign pin triple: `{repo_sha, deploy_sha, runtime_ref}`.
- Every bundle must carry `repo_sha` equal to campaign pin (or be rejected).
- `deploy_sha` / `runtime_ref` required for live/config scope; code-only bundles may set them `NOT_OBSERVABLE` with reason.
- Cited commits must be ancestors of `repo_sha`, else label `other-SHA: not at pin`.

## Evidence bundle (required fields)

See `schema/v1.json`. Incomplete bundles are **rejected** (not softened).

Especially:

- `schema_version: "1"`
- `falsifier: {probe, expected, refutes_if}` — reject literals `N/A`, `none`, `unknown`, empty
- `citations[]` with `sha:path:line`
- `bytes_read` (literal text for smoke / line-range claims) OR structured `NOT_OBSERVABLE` failure
- `fetch_method`: `raw` | `api` | `mc_paste` (required on every code-read bundle)

## Fetch ladder (Tracer / ConfigTruth code reads)

1. **raw** — `https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/<repo_sha>/<path>`
2. On 403 / empty / truncate / tool failure → **api** —  
   `GET https://api.github.com/repos/cryptoreporthub/subnet-dashboard/contents/<path>?ref=<repo_sha>`  
   Decode `content` (base64). Do not trust HTML preview pages.
3. On tool failure → ask **Mission Control** for a bounded paste; set `fetch_method: mc_paste`.
4. Never invent lines from pretraining. If no bytes → `verdict: NOT_OBSERVABLE` with exact error.

## Router rules (Mission Control)

1. Seats do not DM each other. MC carries tickets and bundles as files / paste packs.
2. **Strip before validate:** if a seat reply has prose or markdown fences, MC extracts the first JSON object (strip leading chatter and ```json fences). If no parseable JSON → reject to that seat only.
3. Validate against `schema/v1.json`. On failure → return to producing seat; **never** forward to Ledger.
4. On success → write `bundles/<claim_id>.<seat>.json`; Ledger merges from **files only**.
5. Malformed / chatty / memory-only code claims never enter `claims.jsonl`.

## Line anchors (smoke)

At pin `c9449d6490231373748f19f299ed19d423a1c971`, `TOP_SCORING_UNIVERSE = ...` is at **line 628** (verified). Line 633 is `_PICK_READ_EXECUTOR`, not the assignment.  
PASS requires **exact text match** for the locked assignment and literal bytes for lines **626–630**. Do not widen to a fuzzy window that accepts 633.

Optional: Tracer may report `line_found`; Ledger still requires `locked_assertion.text` substring in `bytes_read` and treats wrong line-number-with-right-text as `partial` + contradiction — not auto-PASS without MC review.

## Pass order

| Pass | Owner | Satisfied when | Blocked when |
|------|-------|----------------|--------------|
| 0 Skeleton | MC | This tree exists; constitution FROZEN | — |
| 0b Smoke | Tracer | `results/SMOKE-001.json` VERIFIED | Fetch failure / wrong bytes |
| 1 F-1 config | ConfigTruth | Live vs code bundles for named keys, or NOT_OBSERVABLE | Probe without Go |
| 2 Contradictions | Ledger | Seeded contradictions registered | — |
| 3 Re-pin claims | Tracer | Section-0 style claims cited at pin | Wrong pin / smoke not VERIFIED |
| 4 Vertical | Tracer | Each hop has bundle or NOT_OBSERVABLE | Hop outside vertical |
| 5 Census | Tracer | Finite grep list committed | `gates/pass4.exit` missing or pin mismatch |
| 6 History | ConfigTruth | Guard timeline cited | `gates/pass6.open` missing |

## Gate files

`gates/*.exit` and `gates/*.open` are JSON:

```json
{"pass": "4", "unlocked_at": "ISO-8601", "by": "joshua|mc", "pin_repo_sha": "<must match campaign>"}
```

Router ignores a gate whose `pin_repo_sha` ≠ campaign `repo_sha`.

## Dedup

`dedup_key = hash(repo_sha, target_seat, normalized_question)`.  
Refuse new ticket if key exists in `queue/open|in_progress|done`.

## Conflict

If two bundles for same `(claim_id, repo_sha, target_seat)` disagree on verdict/edge: keep both, emit contradiction row, leave tier B, escalate. Use `supersedes` for intentional replacements — do not silent-overwrite.

## Smoke invariant (Gate 0b)

Ticket: `queue/open/SMOKE-001.json`.

- **PASS:** Tracer bundle includes literal `server.py` lines **626–630** at campaign `repo_sha`, and `bytes_read` contains  
  `TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))`
- **FAIL / BLOCKED:** 404, empty, truncation without those lines, wrong SHA, prose-only, or `fetch_method` missing.

## Hard claim

No hard claim (e.g. inversion/scoring_cap) until SMOKE-001 is VERIFIED in `results/SMOKE-001.json`.

## Seeded contradictions (register, do not resolve)

See `contradictions.jsonl` seed rows. Includes WORKER_HEAVY essential vs full; wedge “no open items” vs open F-1/B3; blind-subnet 88 vs 126; orphan 720s vs ~18m; proxy inbound vs scorer egress; rediscovery count drift; Tier A citing memory/PR instead of blobs.
