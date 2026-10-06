# Replit Batch 2 — spot-check brief

**PR:** [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324)  
**Branch:** `cursor/audit-evidence-2026-10-05-smoke`  
**Pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129`  
**Review surface:** GitHub PR comments only — **`review_status` source of truth = Replit**

Post verdicts using the comment template in [`REVIEW-WORKFLOW.md`](REVIEW-WORKFLOW.md). MC mirrors PASS/MODIFY/BLOCK into `ledger/claims.json`.

---

## Instructions

1. Check out the PR branch at the **commit SHA cited in the MC handoff comment** (may advance from pin).
2. Execute scopes A–D below.
3. Post **one PR comment per scope** (or per claim_id for Scope D gating set) with raw `git show` / command output.
4. Do **not** merge; Joshua holds Tier B→A + merge.

---

## Scope A — Ledger ↔ findings consistency

**Subject:** `ledger/claims.json` vs `findings/*.json` on the PR branch.

| Criterion | SATISFIED | BLOCKED |
|---|---|---|
| Every `claim_id` in `claims.json` has a matching `findings/{claim_id}.json` | All 26 present | Any missing file |
| Bundle `pin` field equals charter pin (or PR documents head drift) | All match `ce3d8200…` | Pin mismatch without note |
| Required schema fields per [`evidence-bundle-schema.md`](evidence-bundle-schema.md) | All bundles validate | Schema violation |
| `ledger/incidents.json` windows match L2 bundles | A/B/C aligned | Window or id drift |

---

## Scope B — Evidence map REV 2 re-cross-review

**Subject:** [`f-items-prior-evidence-map-2026-10-03.md`](f-items-prior-evidence-map-2026-10-03.md) body + **Appendix REV 2.2** at pin.

| Criterion | SATISFIED | BLOCKED |
|---|---|---|
| REV 2 corrections still hold at `git show ce3d8200:<path>` | Mid-guards, per-cycle executor, revive budget, PR attribution fixes confirmed | Line drift or reverted fix |
| Embedded corrections in appendix (predictions flock, hourly HOLD, C-017 missing) | Anchors reproduce | Wrong anchor or regressed prose |
| Historical measurements remain labeled transcript evidence | Wording intact | Upgraded to runtime proof without receipt |

**Priority git-show anchors:**

```bash
git show ce3d8200:internal/council/resolver.py | nl -ba | sed -n '215,216p'
git show ce3d8200:internal/council/hourly_pick.py | nl -ba | sed -n '86p;139,145p'
git show ce3d8200:internal/council/daily_pick.py | nl -ba | sed -n '284p'
git show ce3d8200:internal/council/resolver_scheduler.py | nl -ba | sed -n '828p;915p;1031,1057p'
ls queue/done/C-0*.json
```

---

## Scope C — candidate-matrix ↔ ledger

**Subject:** [`ledger/candidate-matrix.md`](ledger/candidate-matrix.md) master table vs `ledger/claims.json`.

| Criterion | SATISFIED | BLOCKED |
|---|---|---|
| Exactly **26 rows** — one per `claim_id` | Row count = 26 | Missing or duplicate claim_id |
| `disposition` matches bundle / claims.json | All align | Mismatch |
| `review_status` column matches claims.json (or notes pending Replit) | Consistent | Stale status |
| L1/L2 diagrams include required nodes (boot :310-361, flock domains, hydrate endpoints, incidents A/B/C) | Present | Required node absent |
| Corrections embedded (COCKPIT_PICKS_REGISTRY_CAP, `_proxy_degraded`, single Fly web process) | Spec + matrix agree | Regression |

---

## Scope D — git-show replay (gating claims)

**Gating claim_ids** — Replit MUST run git-show replay and post PASS/MODIFY/BLOCK:

| claim_id | Replay focus |
|---|---|
| SMOKE-001 | `server.py:510-512` StaticFiles |
| SMOKE-002 | `resolver_scheduler.py:735-737` swallow |
| SMOKE-003 | live `/version` vs pin (http-live) |
| C6-WORKER-HEAVY-ESSENTIAL-001 | `fly.toml:41` + boot path skips |
| L2-INC-A-001 | bundle + incident window only (mechanism UNKNOWN) |
| L2-INC-B-001 | bundle + incident window |
| L2-INC-C-001 | bundle + static path count cross-check |
| L2-PERSIST-HYDRATE-001 | persist/hydrate anchors in brief action table |

**All other pending claim_ids — UNVERIFIED until Replit git-show**, with reason:

| claim_id | UNVERIFIED reason (Batch 2 backlog) |
|---|---|
| C1-MAX-SNAPSHOTS-001 | Pending Scope D spot-check |
| C10-PREVIEW-GRADED-HARDCODE-001 | Pending Scope D spot-check |
| C12-STATIC-PATH-COUNT-001 | Pending Scope D spot-check |
| C13-CHECKPOINT-T1_5-001 | Pending Scope D spot-check |
| C2-WATCHLIST-PATH-001 | Pending Scope D spot-check |
| C2-WORKER-PEER-TIMEOUT-001 | Pending Scope D spot-check |
| C3-DATASTORE-PUMP-DEAD-001 | Pending Scope D spot-check |
| C4-FLOCK-SPINLOCK-001 | Pending Scope D spot-check |
| C4-REVIVED-LATCH-001 | Pending Scope D spot-check |
| C5-SQLITE-INVENTORY-001 | Pending Scope D spot-check |
| C8-BARE-EXCEPT-PASS-001 | Pending Scope D spot-check |
| C8-RESOLVER-PERSIST-SWALLOW-001 | Pending Scope D spot-check (related SMOKE-002) |
| C9-TOP-SCORING-UNIVERSE-001 | Pending Scope D spot-check |
| STOP-RULE-SAMPLE-1 | Pending Scope D spot-check |
| STOP-RULE-SAMPLE-2 | Pending Scope D spot-check |

*(9 claim_ids already `replit_pass` from Batch 1 priority sample — re-spot optional, not blocking Batch 2 close.)*

---

## Comment template (from REVIEW-WORKFLOW.md)

```markdown
## Spot-check: {claim_id or Scope X}

**Verdict:** PASS | MODIFY | BLOCK

**Pin:** ce3d820013d45577333ac8aada8c0d9e97c54129

**PR head checked:** {commit_sha}

**Command run:**
\`\`\`bash
git show ce3d8200:server.py | nl -ba | sed -n '510,512p'
\`\`\`

**Raw output:**
\`\`\`
(paste)
\`\`\`

**Notes:** (optional MODIFY/BLOCK rationale)
```

---

## Pending claim_ids (explicit list — 17)

All currently `review_status: pending` in `claims.json`:

1. `C1-MAX-SNAPSHOTS-001`
2. `C10-PREVIEW-GRADED-HARDCODE-001`
3. `C12-STATIC-PATH-COUNT-001`
4. `C13-CHECKPOINT-T1_5-001`
5. `C2-WATCHLIST-PATH-001`
6. `C2-WORKER-PEER-TIMEOUT-001`
7. `C3-DATASTORE-PUMP-DEAD-001`
8. `C4-FLOCK-SPINLOCK-001`
9. `C4-REVIVED-LATCH-001`
10. `C5-SQLITE-INVENTORY-001`
11. `C6-WORKER-HEAVY-ESSENTIAL-001`
12. `C8-BARE-EXCEPT-PASS-001`
13. `C8-RESOLVER-PERSIST-SWALLOW-001`
14. `C9-TOP-SCORING-UNIVERSE-001`
15. `STOP-RULE-SAMPLE-1`
16. `STOP-RULE-SAMPLE-2`
17. `L2-PERSIST-HYDRATE-001`

---

## References

- Merged spec: [`ARCHITECTURE-MAP-V1-SPEC.md`](ARCHITECTURE-MAP-V1-SPEC.md)
- Live diagram: [`ledger/candidate-matrix.md`](ledger/candidate-matrix.md)
- Ditto handoff (after Batch 2): [`DITTO-TICKET-L1L2.md`](DITTO-TICKET-L1L2.md)
