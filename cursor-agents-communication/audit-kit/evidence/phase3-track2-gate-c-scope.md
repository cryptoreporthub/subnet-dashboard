# Phase 3 Track 2 — Gate C read-only scope proposal

| Field | Value |
|---|---|
| Status | **AWAITING_GATE_C** |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| PR | [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Opened | 2026-10-06 (post–Tier A) |

**Gate C applies only to production touch.** No deploy, restart, config mutation, or secrets write.

User “start follow-ups” ≠ automatic prod SSH. Explicit Gate C grant required before execution.

---

## Authorized scope (pending Joshua Gate C write)

### 1. Finding D — two dropped netuids (Grok rev3 FAIL item)

| Item | Detail |
|---|---|
| Problem | 168→166 LOCKED; two dropped netuids UNKNOWN without prod read |
| Read-only method A | `fly ssh console -a subnet-dashboard -C "python3 -c '…'"` on `data/subnet_universe.json` `validity_map` negatives |
| Read-only method B | Diff `/api/subnets` ids vs TaoMarketCap universe |
| Deliverable | Netuid list + receipt in `phase3-finding-d-netuids-*.md` (future) |
| Verdict slot | PENDING |

### 2. F02 q12 prod env (optional)

| Item | Detail |
|---|---|
| Problem | Effective runtime env overrides NOT_OBSERVABLE at pin |
| Read-only method | SSH/console read of effective env (no writes) |
| Deliverable | Row update in candidate-matrix L4 env table or bounded NOT_OBSERVABLE receipt |
| Verdict slot | PENDING |

### 3. Sentry gap-fill (conditional)

| Item | Detail |
|---|---|
| Trigger | Only if Track 1 returns NOT_OBSERVABLE for all three INC windows |
| Scope | Any additional prod read strictly necessary to name mechanism |
| Verdict slot | DEFERRED |

---

## Explicitly out of scope

- `fly deploy`, machine restart/destroy, secrets set/unset
- Volume create/destroy, org changes
- Log drain install (Track 3 — separate approval)

---

## Execution checklist (after Gate C grant)

- [ ] Record Gate C grant text + timestamp in this file
- [ ] Run Finding D read-only probe; paste raw output + exit code
- [ ] Name netuids or document bounded unknown with receipt
- [ ] Optional F02 q12 env read if still needed for matrix
- [ ] Update `claims.json` only with evidence-backed fields (no NOT_OBSERVABLE→CONFIRMED without receipt)
