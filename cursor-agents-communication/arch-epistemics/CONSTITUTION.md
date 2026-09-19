# Campaign Constitution — Architecture Epistemics

**schema_version:** `1`  
**status:** **FROZEN**  
**frozen_at:** `2026-09-19T20:06Z`  
**frozen_by:** Joshua Go (explicit) via Mission Control  
**do_not_edit:** without a new explicit freeze Go  

**campaign_pin.repo_sha:** `c9449d6490231373748f19f299ed19d423a1c971`  
**campaign_pin.deploy_sha:** `NOT_OBSERVABLE`  
**campaign_pin.runtime_ref:** `NOT_OBSERVABLE`

---

## Non-negotiables

1. No claim without `SHA:path:line` **and** literal bytes read (or explicit `NOT_OBSERVABLE`).
2. Filenames / docstrings / PR titles are not behavior; call sites are.
3. Discovery ≠ authorization: no fixes, PRs, deploys, or live probes without Joshua's separate Go.
4. Tier A only after Joshua (or named non-author) spot-checks the exact citation.
5. Grok seats never call Ditto. Memory enters only via Joshua → Ledger as Tier B (`evidence_class: memory`).
6. Mission Control is the only router. Seats communicate through queue/bundle **files**, not prose DMs.
7. Answering from model memory without a recorded `fetch_method` is forbidden.

---

## 1. Three-tier fetch ladder (MANDATORY for code reads)

Order is fixed. Skip ahead only on failure of the prior tier.

| Tier | `fetch_method` | How |
|------|------------------|-----|
| 1 | `raw` | `https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/<repo_sha>/<path>` |
| 2 | `api` | `GET https://api.github.com/repos/cryptoreporthub/subnet-dashboard/contents/<path>?ref=<repo_sha>` then base64-decode `content`. Never trust HTML preview pages. |
| 3 | `mc_paste` | Ask Mission Control for a bounded paste; record `fetch_method: mc_paste`. |

If all tiers fail → `verdict: NOT_OBSERVABLE` with the exact error. **Never invent lines from pretraining.**

### `fetch_method` required

Every **code-read bundle** MUST include:

```json
"fetch_method": "raw" | "api" | "mc_paste"
```

Bundles missing `fetch_method` are **rejected** by MC (not softened, not forwarded to Ledger).  
Ledger merge-only outputs use `"fetch_method": "n/a_ledger_merge"` (not a code read).

---

## 2. Mission Control router — JSON strip rule (MANDATORY)

On every seat reply:

1. **Do not** paste raw chat into Ledger.
2. **Strip before validate:**
   - Drop leading/trailing prose (greetings, "Here is the bundle:", sign-offs).
   - If fenced with ```json / ```, take the inner block.
   - Parse the **first** `{...}` JSON object only.
3. Validate against `schema/v1.json` (including `fetch_method` for code reads).
4. Reject falsifier literals: `N/A`, `none`, `unknown`, empty.
5. If invalid → return to **that seat only**. **Never** forward malformed output to Ledger.
6. If valid → write `bundles/<claim_id>.<seat>.json`; Ledger merges from **files only**.

Malformed / chatty / memory-only code claims never enter `claims.jsonl`.

Full procedure: `ROUTER.md`.

---

## 3. Locked smoke anchor — line 628 (DO NOT WIDEN)

At pin `c9449d6490231373748f19f299ed19d423a1c971`:

| Line | Role |
|------|------|
| **628** | **LOCKED** assignment: `TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))` |
| 626–630 | Required `bytes_read` window (literal) |
| 633 | `_PICK_READ_EXECUTOR` — **not** the assignment; **not** drift |

PASS for SMOKE-001 requires:

- `bytes_read` contains literal lines **626–630**, and
- locked text for line **628** exact-matches, and
- `fetch_method` set.

Do **not** redefine the anchor as a fuzzy window that accepts line 633.

Ticket: `queue/open/SMOKE-001.json`.

---

## Evidence bundle (required fields)

See `schema/v1.json`. Incomplete bundles are **rejected**.

Especially:

- `schema_version: "1"`
- `fetch_method` (see §1)
- `falsifier: {probe, expected, refutes_if}` — reject `N/A` / `none` / `unknown` / empty
- `citations[]` with `sha:path:line`
- `bytes_read` (literal for smoke / line-range) OR structured `NOT_OBSERVABLE`

---

## Pin protocol

- One campaign pin triple: `{repo_sha, deploy_sha, runtime_ref}`.
- Every bundle `repo_sha` must equal campaign pin (else reject).
- `deploy_sha` / `runtime_ref` required for live/config scope; code-only may set `NOT_OBSERVABLE` with reason.
- Cited commits must be ancestors of `repo_sha`, else `other-SHA: not at pin`.

---

## Pass order

| Pass | Owner | Satisfied when | Blocked when |
|------|-------|----------------|--------------|
| 0 Skeleton | MC | This tree exists; constitution FROZEN | — |
| 0b Smoke | Tracer | `results/SMOKE-001.json` VERIFIED | Fetch failure / wrong bytes |
| 1 F-1 config | ConfigTruth | Live vs code bundles, or NOT_OBSERVABLE | Probe without Go |
| 2 Contradictions | Ledger | Seeded contradictions registered | — |
| 3 Re-pin | Tracer | Claims cited at pin | Smoke not VERIFIED |
| 4 Vertical | Tracer | Each hop bundled or NOT_OBSERVABLE | Outside vertical |
| 5 Census | Tracer | Finite grep list committed | `gates/pass4.exit` missing/pin mismatch |
| 6 History | ConfigTruth | Guard timeline cited | `gates/pass6.open` missing |

## Gate files

```json
{"pass": "4", "unlocked_at": "ISO-8601", "by": "joshua|mc", "pin_repo_sha": "<must match campaign>"}
```

Router ignores gates whose `pin_repo_sha` ≠ campaign `repo_sha`.

## Dedup / conflict

- `dedup_key = hash(repo_sha, target_seat, normalized_question)` — refuse duplicates in open|in_progress|done.
- Disagreeing bundles for same `(claim_id, repo_sha, seat)`: keep both, emit contradiction, leave tier B. Use `supersedes` for intentional replace — no silent overwrite.

## Ditto coverify lane

Ditto cross-checks MCP memories against repo bytes. Grok seats never call Ditto.  
Coverify packets must include in one shot: claim_id, repo, pin_sha, path, line/range, claimed_bytes, fetch_method, producer, artifact_path, PR, status, coverify_request=true.  
Pull failure at named SHA = the answer. Output AGREE/DIVERGE per line with deciding file:line.

## Hard claim

No hard claim until `results/SMOKE-001.json` status is **VERIFIED**.
