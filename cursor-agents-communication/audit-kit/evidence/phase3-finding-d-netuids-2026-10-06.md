# Phase 3 Finding D — two dropped netuids (Gate C receipt)

| Field | Value |
|---|---|
| Status | **CONFIRMED** |
| Executed | 2026-10-06T12:36:00Z |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Gate C grant | Joshua granted Track 2 read-only 2026-10-06 |
| Method | A — `fly ssh console` read-only python one-liner on `data/subnet_universe.json` |

---

## Verdict

The **168→166 shrink** in build logs is caused by **two netuids** with `validity: "negative"` in prod `validity_map`:

| netuid | API name | validity | negative_since (UTC) | sources |
|---|---|---|---|---|
| **130** | SN130 | negative | 2026-09-27T20:37:12.969425+00:00 | blockmachine_probe |
| **132** | SN132 | negative | 2026-09-26T22:29:16.178659+00:00 | blockmachine_probe |

**Served universe:** still **168** netuids (0–167) via LKG republish path — matches live `/api/subnets` count=168 @ 2026-10-06T12:35Z.

**Build universe:** **166** — excludes netuids 130 and 132 because both are negative past 48h grace but shrink is blocked (`refresh_incomplete` + `_shrink_allowed` false branch). Static analysis: [`grok-fly-triage-rev3-2026-10-06.md`](grok-fly-triage-rev3-2026-10-06.md) §4D.

---

## Raw receipt (method A)

**Command:**

```bash
flyctl ssh console -a subnet-dashboard -C 'python3 -c "import json; d=json.load(open(\"data/subnet_universe.json\")); neg={k:v for k,v in d.get(\"validity_map\",{}).items() if v.get(\"validity\")!=\"positive\"}; print(\"netuids_count\", len(d.get(\"netuids\",[]))); print(\"validity_map_size\", len(d.get(\"validity_map\",{}))); print(\"negatives\", json.dumps(neg, sort_keys=True))"'
```

**Exit code:** 0  
**Timestamp:** 2026-10-06T12:36:00Z (approx)

**Stdout:**

```
Connecting to fdaa:80:e535:a7b:76d:fe35:72da:2...
netuids_count 168
validity_map_size 168
negatives {"130": {"disputed": false, "negative_since": "2026-09-27T20:37:12.969425+00:00", "refresh_incomplete": true, "sources": ["blockmachine_probe"], "validity": "negative"}, "132": {"disputed": false, "negative_since": "2026-09-26T22:29:16.178659+00:00", "refresh_incomplete": true, "sources": ["blockmachine_probe"], "validity": "negative"}}
```

---

## Corroboration (method B — partial)

| Check | Result |
|---|---|
| `GET /api/subnets` count | 168 (netuids 0–167 inclusive) |
| netuid 130 in API | yes — name `SN130` |
| netuid 132 in API | yes — name `SN132` |
| TMC public table (`api.taomarketcap.com/public/v1/subnets/table/`) | 129 rows; **130 and 132 absent** — TMC is not a full 0–167 baseline (167 ids missing from 0–167 range) |

Method B alone cannot name the two netuids; method A is authoritative.

---

## Ledger impact

- Grok rev3 `carried_over_D_netuids`: **FAIL → PASS** (netuids named with prod read receipt)
- No change to L2-INC-A/B/C `mechanism_status` (incident forensics unchanged)
