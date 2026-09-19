# Campaign Constitution — Architecture Epistemics

**schema_version:** `1`  
**status:** DRAFT until frozen in Cursor plan mode  
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

## Router failure rule (MC)

If Tracer or ConfigTruth returns non-JSON, wrong `schema_version`, or missing required fields:

- MC **rejects** and returns the ticket to that seat only.
- MC **never** forwards malformed output to Ledger.
- Ledger never sees Tracer/ConfigTruth chain-of-thought — bundles only.

## Pass order

| Pass | Owner | Satisfied when | Blocked when |
|------|-------|----------------|--------------|
| 0 Skeleton | MC | This tree exists on a branch | — |
| 1 F-1 config | ConfigTruth | Live vs code bundles for named keys, or NOT_OBSERVABLE | Probe without Go |
| 2 Contradictions | Ledger | Seeded contradictions registered | — |
| 3 Re-pin claims | Tracer | Section-0 style claims cited at pin | Wrong pin |
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

## Smoke invariant (Gate 0)

Ticket: `queue/open/SMOKE-001.json`.

- **PASS:** Tracer bundle includes literal `server.py` lines **626–630** at campaign `repo_sha`, and line 628 equals  
  `TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))`
- **FAIL / BLOCKED:** 404, empty, truncation without those lines, wrong SHA, or prose-only.

Raw fetch pattern (preferred for Grok tools):

`https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/<repo_sha>/server.py`

## Hard claim

No hard claim (e.g. inversion/scoring_cap) until SMOKE-001 is VERIFIED in `results/SMOKE-001.json`.

## Seeded contradictions (register, do not resolve)

See `contradictions.jsonl` seed rows. Includes WORKER_HEAVY essential vs full; wedge “no open items” vs open F-1/B3; blind-subnet 88 vs 126; orphan 720s vs ~18m; proxy inbound vs scorer egress; rediscovery count drift; Tier A citing memory/PR instead of blobs.
