# SimiVision Evidence-Bot Blueprint

## Purpose

This document grounds the proposed SimiVision bot team in the current product and
repository. It is a planning handoff, not an implementation specification. It
records what exists today, what the bots should read, what they must not mutate,
and the safest order for future execution.

## Executive decision

SimiVision should remain the intelligence engine. The bot fleet should be a
supervised control layer around it:

```text
user request or system event
            ↓
      Orchestrator
            ↓
 intent and risk classification
            ↓
 parallel specialist checks
            ↓
      evidence merger
            ↓
 policy and approval gate
            ↓
 answer, incident, or proposed action
```

Do not create a second all-purpose prediction engine. Do not initially split the
bots into separate deployables. The current FastAPI plus worker architecture is
the safest place to add bounded, isolated bot services later.

## Verified product reality

The public product inspected during planning is:

- `https://subnet-dashboard.fly.dev`

The site is a mobile-oriented subnet intelligence dashboard, not primarily a
chatbot. Its visible surfaces include:

- Council consensus using Oracle, Echo, and Pulse
- Confidence, dissent, weighting, and learning
- Live subnet discovery and market signals
- Pump desk and signal feed
- Subnet Summer and message intelligence
- Watchlists, investigations, and portfolio context
- Proof, freshness, and integration status

The site visibly distinguishes states such as `LIVE`, `COLD`, `WARMING`, and
archive mode. It also exposes source and integration status. Any bot that hides
those distinctions would contradict the product's core trust model.

The current Replit workspace does not report an active Replit deployment, so the
Fly URL should be treated as the externally hosted product surface rather than
assumed to be the current Replit deployment.

## Current repository grounding

There is no `internal/bot.py` or `internal/bots/` package today. The relevant
capabilities already exist as focused modules:

| Capability | Current location | Role in the future fleet |
|---|---|---|
| Operational evidence bundle | `internal/ops/evidence.py` | Proof Scout and Sentinel input |
| Evidence population labels | `internal/learning/evidence.py` | Prevent mixing council, shadow, pump, and archive data |
| Message proof classification | `internal/message_intel/proof.py` | Proof Scout input |
| Message-intelligence pipeline | `internal/message_intel/engine.py` | Social evidence and community signals |
| Message-intelligence API | `internal/message_intel/routes.py` | Bounded read and ingest surfaces |
| Learning-loop health | `internal/learning/routes.py` | Sentinel input |
| Readiness aggregation | `internal/ops/readiness.py` | Sentinel input |
| Readiness caching | `internal/ops/readiness_cache.py` | Bounded operator checks |
| Existing Council coordinator | `internal/council/orchestrator.py` | Future routing extension point |
| Daily rotation selector | `internal/council/selector.py` | Existing Council contract; do not replace |
| Background scheduling | `internal/job_scheduler.py` | Future scheduled checks |
| Job boot and separation | `internal/background_boot.py` | Existing essential/heavy job boundaries |
| Worker entrypoint | `internal/worker.py` | Async and volume-owned execution |
| Worker proxy | `internal/worker_proxy.py` | Web-to-worker data boundary |
| Volume ownership rules | `internal/data_volume.py` | Prevent stale web-local reads |

## Answers to the original grounding questions

### Where is the evidence-bot code?

There is no single evidence bot yet. Evidence behavior is distributed across
the modules listed above. The closest existing read-only bot-like surface is
`internal/ops/evidence.py`, while the strongest evidence lineage logic is in
`internal/learning/evidence.py` and `internal/message_intel/proof.py`.

The future fleet should be added as isolated domain modules under a dedicated
bot package only after the shared contract and permissions are agreed. The
initial work should not assume that package already exists.

### What does a real evidence feed look like?

The following is a condensed, sensitive-value-free response captured from the
running application's `/api/ops/evidence` endpoint during planning. Counts and
timestamps are environment data, not fixed test fixtures:

```json
{
  "status": "alert",
  "checked_at": "2026-08-26T22:51:23Z",
  "alerts": [
    "pump_desk alert",
    "council_health ALERT"
  ],
  "paths": {
    "pick_audit": null,
    "pump_desk": "data/pump_desk/latest.json",
    "learning_outcomes": "data/learning_outcomes/latest.json",
    "combined_angles": "data/learning_outcomes/combined_angles_effectiveness.json"
  },
  "pump_desk": {
    "alert_level": "alert",
    "captured_at": "2026-08-26T22:41:03Z"
  },
  "learning_outcomes": {
    "alert_level": "alert",
    "captured_at": "2026-08-26T17:25:38Z",
    "council_health": {
      "health_score": 0,
      "directional_accuracy": 0.0,
      "graded": 2,
      "correct": 0,
      "wrong": 2,
      "integrity_ok": false
    }
  },
  "accuracy_lift": {
    "data_available": true,
    "graded_7d": 33,
    "hit_rate_7d": 0.2727
  }
}
```

This is a multi-source operational evidence bundle, not a single timestamped
blob. Each section has its own capture time and trust implications.

### Which module produces `/api/learning/health`?

The route is defined in `internal/learning/routes.py` by
`api_learning_loop_health`.

The route:

1. Reads the learning-health cache.
2. Returns stale cache data when a refresh is already in flight.
3. Builds health in a bounded worker thread.
4. Returns shape-stable degraded data on timeout or failure.
5. Avoids daily-pick scoring.

Its supporting health information comes from
`internal/learning/loop_health.py`, resolver scheduler state, watchdog state,
pick scheduler state, snapshot age, and worker peer state.

`/api/ops/readiness` is separate. It is aggregated by
`internal/ops/readiness.py` and includes learning health, feed health, worker
state, credentials, and daily-pick advisories.

## Freshness and staleness model

The fleet must distinguish process liveness from evidence freshness.

### Liveness

Answers:

> Is the service or worker alive?

Sources include worker heartbeat, resolver running state, scheduler state, and
the fast liveness report.

### Evidence freshness

Answers:

> Is this particular source current enough to support a claim?

The minimum source envelope should be conceptually equivalent to:

```json
{
  "source": "learning_outcomes",
  "status": "fresh|aging|stale|missing|degraded",
  "captured_at": "2026-08-26T17:25:38Z",
  "age_seconds": 1234,
  "data": {},
  "authoritative": true
}
```

The bot must not label a response as fresh because the HTTP request returned
200. It must inspect the relevant source timestamp, status, and fallback
metadata.

Current important timestamp fields include:

- `checked_at` for the time a health or evidence report was built
- `captured_at` for pump and learning-outcome artifacts
- `last_resolver_tick` for resolver activity
- `last_run_at` and `last_run_ok` for scheduled work
- `snapshot_age_seconds` and source-specific snapshot age
- `last_sync` and `last_sync_at` for feed synchronization
- `last_message_at` and `last_message_age_seconds` for listener data

A future heartbeat can supplement these fields, but it must not replace
source-specific freshness.

### Agreed freshness thresholds

These are the policy thresholds for an artifact's `captured_at` (or the
source-specific equivalent). Bounds are inclusive. An artifact older than the
stale bound remains `stale`; it does not silently become `missing`. `missing`
means that no artifact or timestamp is available. `degraded` means that a
source was present but its read failed, timed out, or was reported unhealthy.

| Source | Fresh | Aging | Stale | Degraded / missing rule |
|---|---:|---:|---:|---|
| Worker heartbeat | ≤2m | ≤5m | ≤15m | failed/unreachable peer is degraded; no heartbeat is missing |
| Resolver tick | ≤15m | ≤30m | ≤60m | failed scheduler is degraded; no tick is missing |
| Live subnet feed | ≤5m | ≤15m | ≤60m | empty/unavailable effective feed is degraded; no sync timestamp is missing |
| Market data | ≤5m | ≤15m | ≤60m | provider/cache error is degraded; no provider timestamp is missing |
| Pump desk | ≤20m | ≤60m | ≤2h | malformed or failed artifact is degraded; absent artifact is missing |
| Pick audit | ≤24h | ≤48h | ≤7d | unreadable audit is degraded; no audit is missing |
| Combined-angle learning | ≤24h | ≤7d | ≤30d | unreadable artifact is degraded; absent artifact is missing |
| Learning health | ≤15m | ≤1h | ≤4h | timeout/error fallback is degraded; no health timestamp is missing |
| Learning outcomes | ≤1h | ≤6h | ≤24h | failed read is degraded; absent outcome artifact is missing |
| Live message intelligence | ≤15m | ≤1h | ≤2h | listener/store failure is degraded; no live message timestamp is missing |
| Archived message intelligence | ≤24h | ≤7d | ≤30d | archive read failure is degraded; no archive artifact is missing |
| GitHub source-of-truth | ≤1h | ≤24h | ≤7d | API/read failure is degraded; no checked revision is missing |

Threshold state never implies liveness. In particular, an alive worker can
serve stale artifacts, and an HTTP 200 can carry a degraded or cached response.
The split web/worker deployment must use the worker heartbeat and worker-owned
artifact timestamps; orphan web-local files are not authoritative.

Message intelligence additionally carries `mode: live|archive`. Archive data
can be fresh as an archive artifact, but it is never authoritative for a
current-live claim: its envelope must set `authoritative: false` and
`claim_scope: historical` (or the equivalent caller-visible annotation).

## Source-of-truth boundaries

| Data | Authoritative source | Important rule |
|---|---|---|
| Active subnet membership | Live chain/RPC feed and last-known-good cache | Static registry is metadata/fallback, not live membership |
| Subnet metadata | `config/registry.json` and approved metadata sources | Do not use it to claim current chain activity |
| Market values | Existing merged-data priority: Blockmachine, TaoStats, TaoMarketCap | Report the source that supplied each value |
| Learning totals | Shared learning read model and prediction stores | Do not recalculate totals independently per bot |
| Council state | Existing Council and Mindmap contracts | Do not create a parallel prediction engine |
| Message evidence | Message-intel store, proof classification, Telegram/Discord status | Archive mode is not live listener mode |
| Worker-owned artifacts | Worker volume through the established proxy boundary | Do not trust orphan web-local files in split mode |
| Readiness | `/api/ops/readiness` and its cached builder | Treat advisory and blocking issues separately |

## Bot fleet

### Orchestrator

The Orchestrator is supervisory only. It:

- Classifies intent and risk
- Selects specialists
- Runs independent checks in parallel
- Merges evidence
- Resolves conflicts
- Applies approval policy
- Produces one answer or proposed action

It must not directly mutate Soul-Map, learning records, registry files, worker
caches, or deployment state.

The existing `internal/council/orchestrator.py` is a coordination starting
point, but its existing daily-rotation behavior must remain distinct from
general bot routing.

### Sentinel — health and uptime

Sentinel monitors:

- API errors and latency
- Worker saturation
- Resolver and watchdog state
- Feed synchronization
- Cache age
- Scheduler failures
- Learning-loop degradation
- Deployment regressions

Sentinel is read-only by default. It may propose remediation but cannot restart,
redeploy, or change infrastructure without approval.

### Drift / QA — silent failure detection

Drift / QA checks:

- API response-shape changes
- Missing fields
- SSR and hydration divergence
- Panels stuck in loading state
- Stale data presented as live
- Summary and stats disagreement
- Degraded metadata being dropped
- Resolver, learning, and scenario totals diverging

This bot is especially important because the product can return HTTP 200 while
the visible dashboard is cold, warming, archived, or only partially hydrated.

### Proof Scout — evidence and provenance

Proof Scout:

- Finds support and contradiction for a claim
- Attaches source and capture timestamps
- Checks evidence population
- Separates live, cached, stale, and archived evidence
- Uses message-intel, GitHub, social, Council, and learning evidence
- Produces an auditable evidence bundle

It should never convert an ungradeable record into a trustworthy one.

### Market Desk — subnet analysis

Market Desk replaces the proposed “Oracle” fleet name because Oracle already
exists as a visible Council role alongside Echo and Pulse.

Market Desk:

- Explains subnet movements and signal changes
- Compares current and historical observations
- Uses existing Council outputs and learning state
- Separates observed facts, inferences, and unknowns
- Reports source and freshness

It does not override SimiVision or issue guaranteed financial conclusions.

### Shield — security and abuse

Shield monitors:

- Suspicious request patterns
- Scraping and crawler behavior
- Repeated expensive endpoint calls
- Prompt abuse
- Authentication failures
- Operational endpoint probing

Shield may propose rate-limit or access changes. It cannot block users, alter
security policy, or revoke access autonomously.

### Concierge — bounded user assistant

Concierge handles:

- Product navigation
- Dashboard terminology
- Signal and confidence explanations
- Proof and freshness explanations
- Watchlist and investigation guidance
- Product FAQs

Concierge must not execute trades, provide individualized financial advice,
override Council state, expose operational internals, or mutate user state
without an explicit approved workflow.

### Content Curator — approved publishing assistant

Content Curator is a later-phase role. It may draft release notes, product
copy, summaries, and documentation from GitHub and verified evidence.

The workflow is:

```text
draft → human review → approved source-of-truth change → normal release process
```

It must not publish directly.

## Shared bot output contract

Every specialist should return a common structure:

```json
{
  "bot": "proof_scout",
  "run_id": "unique-run-id",
  "status": "ok|degraded|blocked",
  "subject": "SN65",
  "summary": "Short plain-English conclusion",
  "observations": [],
  "evidence": [],
  "unknowns": [],
  "confidence": 0.0,
  "freshness": {
    "status": "fresh|aging|stale|missing|degraded",
    "observed_at": null,
    "age_seconds": null,
    "sources": []
  },
  "recommended_action": null,
  "approval_required": false,
  "approval": {
    "required": false,
    "status": "not_required|pending|approved|rejected",
    "action_category": null,
    "approver_role": null,
    "surface": null,
    "approval_id": null,
    "approved_at": null
  },
  "audit": {
    "sources_read": [],
    "duration_ms": 0
  }
}
```

`confidence` is a bounded value from `0.0` to `1.0`, or `null` when the
response is observational rather than a scored conclusion. `approval_required`
must agree with `approval.required`. A state-changing recommendation is never
approved by default.

The Orchestrator should downgrade or block synthesis when required evidence is
missing, stale, contradictory, or unavailable.

## Permission boundaries

| Role | Read | Propose | Mutate |
|---|---:|---:|---:|
| Orchestrator | Yes | Yes | No |
| Sentinel | Yes | Yes | No |
| Drift / QA | Yes | Yes | No |
| Proof Scout | Yes | Yes | No |
| Market Desk | Yes | Yes | No |
| Shield | Yes | Yes | No |
| Concierge | Limited | No | No |
| Content Curator | Yes | Draft only | No |

No bot may autonomously:

- Edit `config/registry.json`
- Edit `data/soul_map.json`
- Write prediction or learning outcomes
- Change learned weights
- Restart or redeploy services
- Block users or IP addresses
- Publish content
- Move funds or execute trades
- Delete data

All state-changing proposals require a human approval record.

### Approval workflow

The human approval surface is a review queue with an append-only approval
record. A proposal enters the queue as `pending`; the bot may explain or
prepare it but may not execute it. The record includes the proposal, evidence
source envelopes, freshness at decision time, confidence, requester, reviewer,
decision, timestamp, and an idempotency/run identifier. Approval expires when
required evidence crosses its stale threshold or becomes degraded.

| Action category | Who may approve | Review surface | Examples |
|---|---|---|---|
| Infrastructure | Platform operator | Operator review queue | restart, redeploy, scaling, worker, or configuration changes |
| Security | Security operator | Security review queue | rate limits, access changes, blocks, or credential policy |
| Learning | Learning owner | Learning review queue | weight changes, grading corrections, or learning-record writes |
| Content / publishing | Content owner | GitHub pull request | release notes, product copy, documentation, or publishing |

The approver must be a human with the named role, not the proposing bot or an
unrelated viewer. Drafting content is not publishing; publishing still
requires the content-owner approval and the normal GitHub source-of-truth
release process. Read-only answers and non-state-changing drafts use
`approval.status: not_required`. An unclassified state-changing proposal fails
closed and is routed to the designated owner in the operator review queue.

## Request routing examples

### “Why is SN65 underperforming?”

```text
Orchestrator
  → Market Desk
  → Proof Scout
  → Sentinel if freshness is questionable
  → evidence merger
```

The answer must separate market observations, Council interpretation, historical
learning, supporting evidence, and unknowns.

### “The dashboard feels stale”

```text
Orchestrator
  → Sentinel
  → Drift / QA
  → readiness and freshness checks
```

The result should identify whether the issue is the web process, worker, RPC,
cache, resolver, or frontend hydration.

### “Is this signal trustworthy?”

```text
Orchestrator
  → Proof Scout
  → Market Desk
  → shared learning read model
  → Sentinel when source age is uncertain
```

The answer should return a trust assessment with evidence and freshness, not
only a directional opinion.

### “Draft a release note”

```text
Orchestrator
  → Content Curator
  → GitHub source-of-truth review
  → human approval
```

## Safest execution sequence

### Phase 0 — contract and policy

- Agree on the shared task and output envelopes.
- Define freshness states and confidence rules.
- Define read-only permissions and approval gates.
- Define audit and run identifiers.

### Phase 1 — Sentinel and Drift / QA

- Monitor readiness, worker, resolver, feed, and cache evidence.
- Add synthetic checks for silent UI and API failures.
- Prove that stale and degraded states are visible.

### Phase 2 — Proof Scout and Market Desk

- Build evidence-backed subnet explanations.
- Preserve source attribution and evidence populations.
- Use the existing Council and learning contracts.

### Phase 3 — Orchestrator synthesis

- Fan out independent specialist checks.
- Merge evidence and resolve conflicts.
- Enforce bounded response times and explicit degraded answers.

### Phase 4 — Concierge

- Expose only safe read-only explanations and navigation.
- Route complex questions through the Orchestrator.

### Phase 5 — Shield and Content Curator

- Add security recommendations and human-approved content workflows.

## Acceptance criteria for future implementation

The first implementation should not be considered ready until:

- Every bot response identifies its evidence sources and freshness.
- A stale source cannot produce a “fresh” conclusion.
- Worker-owned data is not replaced by web-local fallback files.
- Council, learning, and message evidence remain separate populations.
- Conflicting specialist results are surfaced rather than silently averaged.
- State-changing recommendations require explicit approval.
- `/health` remains responsive while heavier checks are running.
- The fleet does not add duplicate scheduler loops or blocking work to request
  paths.
- A cold, warming, archive, or degraded dashboard state is communicated honestly.

## Remaining implementation decisions

The freshness thresholds and approval roles/surfaces above are settled policy.
The following are intentionally deferred implementation choices:

1. Should approval audit records use the existing file/SQLite stores or a
   separate append-only store?
2. Which users may access Concierge, and which operational details must remain
   operator-only?
3. Which GitHub actions, if any, may be proposed automatically?
4. What is the required maximum latency for synchronous user questions?
5. Which production logs are available to Sentinel, given that the current
   Replit workspace and public Fly site are separate deployment contexts?