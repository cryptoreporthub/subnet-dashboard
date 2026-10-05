# Evidence Bundle schema (Lane 1 & Lane 2)

Every **CONFIRMED** or **Tier A** finding must have a JSON bundle on disk.
Prose in the candidate matrix is not sufficient on its own.

**Output directory:** `cursor-agents-communication/audit-kit/findings/`  
**Naming:** `{claim_id}.json` (e.g. `C5-STATIC-001.json`, `L2-INC-B-001.json`)

## Required fields

| Field | Required | Notes |
|---|---|---|
| `claim_id` | yes | Stable ID; new audit — do not reuse old `queue/done/` IDs without re-pin |
| `title` | yes | One-line claim |
| `pin` | yes | Full 40-char SHA (`ce3d820013d45577333ac8aada8c0d9e97c54129`) |
| `lane` | yes | `1` (static) or `2` (runtime) |
| `class` | yes | `C1`–`C13`, or `L2-INC-A` / `L2-INC-B` / `L2-INC-C` for incident windows |
| `disposition` | yes | `CONFIRMED` / `REFUTED` / `BY-DESIGN` / `UNKNOWN` |
| `refutes_if` | yes | Concrete observation that would disprove the claim — not `N/A` |
| `fetch_method` | Lane 1 yes | **Git-clone replayable only** — `git show <pin>:path`, `git cat-file`, AST scan with exit code. No API-only methods (Ditto must translate GitHub API reads into equivalent `git show` for Replit) |
| `evidence` | yes | Array of objects or strings; prefer objects with `path`, `lines`, `quote` (verbatim span at pin). Enough for Replit to diff on span, not formatting |
| `tier` | yes | `B` until Joshua spot-check; then `A`. Lane 2 prod facts stay `B`/`PROD-OBSERVED` unless independently re-verified |
| `verified_by` | optional | Seat that produced the bundle (`lane1`, `lane2`, `ditto-code`, `lane2`) |
| `conflicts_with` | optional | Ditto/Cursor flag only — `claim_id` or `path:lines` of overlapping bundle; **MC** writes `ledger/contradictions.json` |

## Example (Lane 1, code-only)

```json
{
  "claim_id": "SMOKE-001",
  "title": "StaticFiles mounted at /static",
  "pin": "ce3d820013d45577333ac8aada8c0d9e97c54129",
  "lane": 1,
  "class": "C5",
  "disposition": "CONFIRMED",
  "refutes_if": "git show pin:server.py lacks StaticFiles mount at :510-512",
  "fetch_method": "git show ce3d8200:server.py | nl -ba | sed -n '510,512p'",
  "evidence": [
    "server.py:510 _static_dir = os.path.join(BASE_DIR, \"static\")",
    "server.py:512 app.mount(\"/static\", StaticFiles(directory=_static_dir), name=\"static\")"
  ],
  "tier": "B",
  "verified_by": ["lane1"]
}
```

## Example (Lane 2, prod-observed)

```json
{
  "claim_id": "L2-INC-B-001",
  "title": "Health probes timed out during 11:41:30–11:47:23Z window",
  "pin": "ce3d820013d45577333ac8aada8c0d9e97c54129",
  "lane": 2,
  "class": "L2-INC-B",
  "disposition": "UNKNOWN",
  "refutes_if": "Fly logs show /health 200 with p99 <1s throughout 11:41–11:47Z",
  "fetch_method": "fly logs --app subnet-dashboard (L2.2); timestamp-filtered excerpt",
  "evidence": ["Gemini task-279 report — re-derive under L2 envelope"],
  "tier": "B",
  "verified_by": ["lane2"]
}
```

## `fetch_method` rule (Replit replay)

Every Lane 1 / Ditto-code bundle must use commands runnable after:

```bash
git fetch origin && git checkout <pin>
```

**Allowed:** `git show ce3d8200:server.py | nl -ba | sed -n '510,512p'`, `git cat-file -p ce3d8200:path`

**Not allowed alone:** "GitHub contents API", "Ditto read at pin" — translate to `git show` equivalent in `fetch_method`.

Independent rerun is proven **after** publication (Replit on PR). Producers do not self-assert replayability beyond using this format.

## Legacy bundles

Files under `queue/done/` from the Architecture Epistemics campaign (pin `c9449d64…`)
are **historical only**. Do not promote to Tier A without re-verification at
`ce3d820013d45577333ac8aada8c0d9e97c54129`.
