# Cursor handoff — source cap inventory and full-active scoring

# Artifact usage

The source HTML report and CSV register are review outputs; this handoff is the implementation and safety contract.


## Artifact guide

- `source-caps-audit.html` is the human-review view: start with its category/effect summary, then use the detailed rows and linked GitHub source citations to inspect evidence.
- `source-cap-register.csv` is the machine-readable register: 2,119 detail rows with scope, kinds, names, path, line, evidence, source URL, and status. Use a spreadsheet or script to filter, sort, group, and reproduce counts.
- The CSV citations are pinned to source commit `9535c3c2a494293f9a11167ee581574f338d2097`. This is a historical source snapshot; current `main` has moved. Refresh the source before implementation.
- All register rows are marked `source-discovery; effective runtime and removal decision not verified`. Neither file proves a cap is active in production or safe to remove; they are an inventory, not a live-runtime verdict.

Read the pinned source inventory described below; refresh live main/PR/production version before implementation.
The user says the old 40-input snapshot limit was needed at the time but is now obsolete. Desired scope: every active non-root alpha subnet (currently128;129 including Root). Resolve membership dynamically; do not replace40 with another magic constant.

## Priority findings
1. Server TOP_SCORING_UNIVERSE defaults20, engine/audit defaults40 and scheduler cap24. Default composition restricts scheduler to20, direct engine/audit to24, snapshot configured40. Unify actual intended coverage across creation, snapshot, replay and hot paths; no silent conflicting defaults.
2. tradable_subnets only excludes invalid/root IDs. It does not establish active membership. Shared display universe includes166 rows while129 rows carry status=active. Provider status is not authoritative chain proof. Define the authoritative membership source and explicit handling for unknown/stale membership; keep Root out of alpha scoring without hiding it from network displays.
3. Snapshot count=len(inputs), while per-item scoring exceptions are swallowed. Emit attempted/succeeded/failed/netuid coverage and actionable failures. A complete snapshot must not claim128-success coverage if fewer results exist.
4. Fresh previous snapshot ranking followed by slicing can keep previously scored names selected and unscored names deprioritized. Full-active selection must not rely on a capped prior snapshot to decide eligibility.
5. Separate count caps from bounded concurrency, provider rate policies, request pagination, retention, cache-byte bounds and score/business clamps. Do not remove every discovered bound.

## Root-cause and rollout gate
 prove the underlying workload rather than increase deadlines or resources. Existing resolver telemetry shows36.1s summary RMW; its relation to snapshot cost is not proven. Keep timeout/shared-state investigation separate but test shared contention.
Satisfied conditions: exact active membership set; Root policy explicit; all active non-root IDs attempted and successfully persisted (or explicit failed state); consistent primary/audit inputs; measured bounded memory and execution under shared web/worker load; no overlapping abandoned workers or late overwrites.
Blocked/unknown: actual Fly override values, process RSS/headroom, full-active per-subnet cost, source completeness/chain-active proof, and empirical proof every old cap is obsolete.
Do not mutate production, raise caps/deadlines, merge or deploy without the user's separate approval. Work on an appropriately scoped branch and push authorized corrections for live GitHub verification. Do not attach unrelated cap work to listener PR1348.
Rollback triggers for an approved later rollout: missing active IDs, falsely green incomplete scoring, memory growth/OOM, sustained request failures, overlapping jobs, stale/late snapshot overwrite, or broken daily-pick/audit parity.
