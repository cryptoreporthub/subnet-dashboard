# Cursor handoff — source cap inventory and full-active scoring

# Artifact usage

The source HTML report and CSV register are review outputs; this handoff is the implementation and safety contract.


## Artifact guide

- `source-caps-audit.html` is the human-review view: start with its category/effect summary, then use the detailed rows and linked GitHub source citations to inspect evidence.
- `source-cap-register.csv` is the machine-readable register: 2,119 detail rows with scope, kinds, names, path, line, evidence, source URL, and status. Use a spreadsheet or script to filter, sort, group, and reproduce counts.
- The CSV citations are pinned to source commit `9535c3c2a494293f9a11167ee581574f338d2097`. This is a historical source snapshot; current `main` has moved. Refresh the source before implementation.
- All register rows are marked `source-discovery; effective runtime and removal decision not verified`. Neither file proves a cap is active in production or safe to remove; they are an inventory, not a live-runtime verdict.

## Source and observation pins

- Inventory source baseline: `9535c3c2a494293f9a11167ee581574f338d2097`.
- Historical production observations in the HTML: 2026-10-10 10:13:43–10:13:46 UTC, when `/version` and GitHub main both reported that baseline. Preserve these historical observations; do not relabel them with a newer SHA.
- Later production `/version` observation: `5d840ba473d2fac9011625ab608e5a97f1028bd0` at 2026-10-10 13:06 UTC, recorded in the [production follow-up](https://github.com/cryptoreporthub/subnet-dashboard/pull/1348#issuecomment-6097901069).
- GitHub main independently refreshed for this documentation update: `89dd2ba083230f6599a7b08e5e2863ae2d4441b3`. This is distinct from the observed deployed revision.

Before any implementation PR, refresh live main, relevant PR heads and production `/version`; re-scan at the selected exact source SHA (`5d840ba4…` or the then-current main head). Review intervening diffs and preserve the old inventory as historical evidence. None of these pins asserts that a value remains current after its observation.

## P0 — scoring universe and production timeouts

Start with the HTML's dedicated P0 view, then its linked curated evidence. P0 here is triage order, not proof that every listed bound is a critical defect.

- Coverage defaults: server `TOP_SCORING_UNIVERSE=20`, engine/audit `TOP_SCORING_UNIVERSE=40`, scheduler policy cap `24`, and deployment declaration `SCORE_SNAPSHOT_MAX_SUBNETS=40`.
- Deployment timeout declarations: `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS=480` and `LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS=90`. These are work budgets, not proof that full-active scoring is safe or that increasing them repairs the underlying workload.
- Retain the complete all-caps CSV. A focused view supplements it; do not discard display, retention, concurrency, provider or other candidates merely because they are outside scoring.
- Cursor/MC follow-up: MC reports 88 rows for its proposed predicate over the unchanged CSV at pin `9535c3c2` ([predicate and count](https://github.com/cryptoreporthub/subnet-dashboard/pull/1353#issuecomment-6102115610)). This is MC's reported count, not an independently reproduced result; the optional filtered CSV is not included. Preserve the complete inventory. Reconcile the predicate/count before treating a derivative subset as validated.

## Count reconciliation

The CSV and HTML discovery table contain the same **2,119 unique path/line rows**, with matching ordered locations and literal evidence. The HTML curated table is a separate **42-bound** review subset, not a category partition of the CSV.

CSV scope counts are disjoint: **2,003 application/config + 65 alternate-deployment + 51 tooling = 2,119**. `kinds` is multi-label: splitting it on semicolons yields **2,334 tag memberships**, including **744 clamp/lower-bound candidates** and **590 slice/truncation candidates**. Overlapping kind totals must not be forced to sum to the unique row count.

## Web vs worker effective caps

| Variable | Source default or deployment declaration | Effective web value | Effective worker value |
| --- | --- | --- | --- |
| `TOP_SCORING_UNIVERSE` | Server default 20; engine/audit default 40; no declaration in inspected `fly.toml` | UNKNOWN | UNKNOWN |
| `PICK_SCHEDULER_UNIVERSE_CAP` | Source default 24 | UNKNOWN | UNKNOWN |
| `SCORE_SNAPSHOT_MAX_SUBNETS` | Inspected `fly.toml` declaration 40 | UNKNOWN | UNKNOWN |
| `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS` | Inspected `fly.toml` declaration 480 | UNKNOWN | UNKNOWN |
| `LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS` | Inspected `fly.toml` declaration 90 | UNKNOWN | UNKNOWN |

Source declarations are not process-effective proof. If a separately approved read-only probe is needed, inspect only allowlisted cap variables and default resolution in the correct web/worker process context. Do not dump unfiltered `printenv` output or credentials. An SSH shell environment alone does not establish child-process overrides. No environment probe was performed for this documentation update.

Read the pinned source inventory described above and refresh the evidence before implementation.
The user says the old 40-input snapshot limit was needed at the time but is now obsolete. Desired scope: every dynamically established active non-root alpha subnet. The user described the population as 128 non-root / 129 including Root; the historical provider labels supported those numbers, but current authoritative chain membership remains unverified. Resolve membership dynamically; do not replace 40 with another magic constant.

## Priority findings
1. Server `TOP_SCORING_UNIVERSE` defaults to 20, while engine/audit `TOP_SCORING_UNIVERSE` defaults to 40; the scheduler cap is 24. Default composition restricts the scheduler to 20, direct engine/audit to 24, and snapshot input to configured 40. Unify intended coverage across creation, snapshot, replay and hot paths; avoid conflicting defaults.
2. tradable_subnets only excludes invalid/root IDs. It does not establish active membership. At the historical 10:13 UTC observation, the shared display universe had 166 rows, of which 129 were provider-labelled status=active including Root. Provider status is not authoritative chain proof. Preserve a raw, pinned production or chain receipt and its field definitions before making current membership claims. Define the authoritative membership source and explicit handling for unknown/stale membership; keep Root out of alpha scoring without hiding it from network displays.
3. Snapshot count=len(inputs), while per-item scoring exceptions are swallowed. Emit attempted/succeeded/failed/netuid coverage and actionable failures. A complete snapshot must not claim full-active success coverage if fewer results exist.
4. Fresh previous snapshot ranking followed by slicing can keep previously scored names selected and unscored names deprioritized. Full-active selection must not rely on a capped prior snapshot to decide eligibility.
5. Separate count caps from bounded concurrency, provider rate policies, request pagination, retention, cache-byte bounds and score/business clamps. Do not remove every discovered bound.

## Root-cause and rollout gate
Prove the underlying workload rather than increase deadlines or resources. The historical 10:13 UTC observation reported 36.1s summary RMW; its relation to snapshot cost is not proven. Keep timeout/shared-state investigation separate but test shared contention.
Satisfied conditions: exact active membership set; Root policy explicit; all active non-root IDs attempted and successfully persisted (or explicit failed state); consistent primary/audit inputs; measured bounded memory and execution under shared web/worker load; no overlapping abandoned workers or late overwrites.
Blocked/unknown: actual Fly override values, process RSS/headroom, full-active per-subnet cost, source completeness/chain-active proof, and empirical proof every old cap is obsolete.
Do not mutate production, raise caps/deadlines, merge or deploy without the user's separate approval. Work on an appropriately scoped branch and push authorized corrections for live GitHub verification. Do not attach unrelated cap work to listener PR1348.
Rollback triggers for an approved later rollout: missing active IDs, falsely green incomplete scoring, memory growth/OOM, sustained request failures, overlapping jobs, stale/late snapshot overwrite, or broken daily-pick/audit parity.
