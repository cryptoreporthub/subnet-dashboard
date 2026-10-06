# Grok Fly triage rev3 receipt (PR #1324)

| Field | Value |
|---|---|
| Ditto memory | `e7639072-c408-48cd-8d00-854591ddf623` |
| Prompt checklist | Ditto `8e03bc78-0cbe-434d-a6d4-8d84eced9dc0` (rev-3 PASS) |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Branch | `cursor/audit-evidence-2026-10-05-smoke` (PR #1324) |
| Folded by | Mission Control worker 2026-10-06 |
| MC review verdict | **PARTIAL** on rev-3 checklist (see below) |

**Checklist review (Grok report vs rev-3 deliverables):**

| # | Deliverable | Verdict | Notes |
|---|---|---|---|
| 1 | Auth reconciliation | PASS | flyctl `d8538a66…@tokens.fly.io`; app=`subnet-dashboard` (not `nameless-cloud-1398`) |
| 2 | 502 root cause 04:38–04:56Z | PARTIAL | crash/OOM/health-fail REFUTED (90/90 HTTP 200); routing/proxy LEADING not CONFIRMED (no proxy lines) |
| 3 | Incident forensics A/B/C | PARTIAL | All NOT_OBSERVABLE with per-method errors — valid gate; no log-line upgrade |
| 4 | Carried-over D (two netuids) | FAIL | 168→166 LOCKED; two dropped netuids UNKNOWN (no prod read authorized) |
| 5 | Endpoint sampler ≥5 min | PASS | 11:48:40–11:54:31Z STALE/degraded measured |
| 6 | Resolver drift stretch | PARTIAL | 82.6m NOT CONFIRMED; max log gap 59.95m |
| 7 | Signal cross-check @ timestamp | PARTIAL | council busy/empty; endpoints timed out → NOT_OBSERVABLE |
| 8 | What I could not prove | PASS | Honest boundaries documented |

**Incident forensics table (folded into bundles + ledger):**

| claim_id | window UTC | mechanism verdict | key log lines | methods + errors if NOT_OBSERVABLE |
|---|---|---|---|---|
| L2-INC-A-001 | 08:29–08:55 | NOT_OBSERVABLE | 0 lines (buffer earliest 04:38:56Z prior / 11:33:11Z current) | (a) 0 overlap (b) `--start` unsupported (c) no drain (d) logs API skipped — token extract blocked by policy |
| L2-INC-B-001 | 11:41:30–11:47:23 | NOT_OBSERVABLE | 0 lines | same four methods |
| L2-INC-C-001 | 11:44–11:54 (center 11:49:15) | NOT_OBSERVABLE | 0 lines | same four methods |

Prior static receipts (phase2, GHA 37283988892, GraphQL lifecycle) retained; `mechanism_status` stays **BOUNDED_UNKNOWN** — no NOT_OBSERVABLE→CONFIRMED upgrade.

---

# subnet-dashboard Fly triage rev3 — PR #1324 forensics (READ-ONLY)
Generated 2026-10-06 ~12:00Z (05:00 AZ). Collector: executor subagent, for Joshua Riley.
Nothing was committed, deployed, restarted, or written to config. I didn't open any secrets.
Artifact dir: `/workspace/fly-triage-rev3-2026-10-06/`

## 0. Setup + HEAD
- Repo: fresh read-only clone `repo/` of cryptoreporthub/subnet-dashboard, branch `cursor/audit-evidence-2026-10-05-smoke` (none of the existing /workspace checkouts had the pin object).
- `git rev-parse HEAD` = **0a43cd5d1001b98b96da603239c8a4621ec5eae5** (commit time 2026-10-06T03:38:15Z).
- Pin ce3d820013d45577333ac8aada8c0d9e97c54129 is an ancestor. **DRIFT: HEAD is 43 commits ahead.** The diff is evidence/docs/JSON only (bundles/, results/, queue/, cursor-agents-communication/, docs/). It changes no `.py` files, so the code at the pin is the code at HEAD. Code line refs below are @ ce3d8200 (checked out detached for the grep, then back on the branch). See `head.txt`.
- Prod `/version` returned `"version": "ce3d8200…"` 24/24 times during the sampler, so prod is running the pin.

## 1. Auth reconciliation
| cmd | exit | result | file |
|---|---|---|---|
| `flyctl auth whoami` | 0 | `d8538a66-fa57-596c-9844-301a9cc108d2@tokens.fly.io`, the same identity as the 2026-10-05 ~22:00 PT receipt | whoami.txt |
| `flyctl status -a subnet-dashboard --all` | 0 | machine 7841024b3712e8 v2274 sjc started, 1/1 checks passing, LAST UPDATED 2026-10-06T11:12:44Z | status-all.txt |
| `flyctl status -a nameless-cloud-1398 --all` | 1 | `Could not find App "nameless-cloud-1398"`. That string is the **machine name**, not an app (machine-status.txt `Name │ nameless-cloud-1398`) | status-all-nameless-cloud-1398.txt |
| `flyctl orgs list` / `apps list` | 0 | a single personal org, one app (subnet-dashboard) | orgs-list.txt, apps-list.txt |

**App name that works: `subnet-dashboard`.** The flyctl token works. The earlier Mission Control REST 401 (`GET api.fly.io/api/v1/apps/subnet-dashboard/logs` with `$FLY_API_TOKEN`, per evidence/l2-inc-phase2…03:36:37Z.txt:33-37) used a different credential/path (an env var `FLY_API_TOKEN`, not the flyctl config token). The two don't conflict: flyctl auth is valid, and the env-var token was rejected. I did not re-test REST (see §8).

## 2. 502 root cause, 2026-10-06T04:38:56Z–04:56:50Z
Sources: the current buffer can't reach this window. `flyctl logs -a subnet-dashboard --no-tail` (exit 0) returned 100 lines, earliest **2026-10-06T11:33:11Z**. A second pull at ~11:57Z had earliest 11:51:08Z. So the only receipt is the prior pull `/workspace/sd-fly-logs-plain.txt`, which is byte-identical to `/tmp/sd-fly-logs-plain.txt` (sha256 c2c0b4dd692d5baa…), 100 lines, 04:38:56Z–04:56:50Z. Filtered copy: `window-502.txt` (0 CUR lines, 100 PRIOR lines).
`--start/--end`: **unsupported** in flyctl v0.4.99. The help flags list only `-a -c -h -j -m -n -r -s`. Attempt: `flyctl logs -a subnet-dashboard --no-tail --start 2026-10-06T04:38:00Z` → exit 1 `Error: unknown flag: --start` (logs-help.txt, logs-start-attempt.txt).

What's in the window (receipts from window-502.txt):
- 90 HTTP access lines, **90/90 status 200, 0 5xx**: 72× `GET /health` from 172.19.37.153 (Fly checker, every 15s), 18× `GET /` from 172.16.37.154 (every ~60s via proxy). Examples: `2026-10-06T04:39:04Z … "GET /health HTTP/1.1" 200 OK`, `2026-10-06T04:39:38Z … "GET / HTTP/1.1" 200 OK`, `2026-10-06T04:56:50Z … "GET /health HTTP/1.1" 200 OK`.
- **0 `health[` check-failure lines, 0 `proxy[` lines**, no crash/exit/OOM lines. The only errors are Telegram 403 (§4C).
- Machine events: no event in the window. Prior status showed last update 2026-10-06T01:17:17Z. The next events are restarts at 10:40:49Z and 11:12:42Z (see below), so there was no restart or image change during 04:38–04:56. Releases: v2274 (Oct 2 00:40, image deployment-01M3X0VF4BNDV9BPAT2HBVSH4W) is current, with no transition on Oct 5–6 (releases.txt).

**Verdict: crash/OOM is ruled out for this window, and so is a Fly health-check failure (0 failure lines, checks passing, steady 15s 200s). Routing/proxy stays the leading hypothesis, but it is NOT CONFIRMED because the buffer has no fly-proxy error line (e.g. "could not find a good candidate").** The app was serving 200s to proxied `/` requests every minute during the window, so the external 502 never reached the app.

New and adjacent (not in the window, CONFIRMED with receipts): today's machine shows a recurring SIGKILL plus health-check flaps. These are a real 502 mechanism:
- machine-status.txt Event Logs: `stopped exit 2026-10-06T04:12:42.121-07:00 exit_code=137,oom_killed=false,requested_stop=false` (= 11:12:42Z); restart at 03:40:49-07:00 (= 10:40:49Z). Restarts are 31m53s apart, exit 137 (SIGKILL), not OOM. flyctl shows only 5 events, so I couldn't see further back.
- logs-no-tail-plain-2.txt: `11:51:44Z health[…] [error]Health check 'servicecheck-00-http-8080' … has failed … Services exposed on ports [80, 443] will have intermittent failures`, then passing at 11:52:00Z. It failed again at 11:52:38Z, 11:53:15Z, and 11:55:32Z. Then there were no app lines from 11:55:57Z to 11:57:09Z.
- **Caveat:** these flaps overlapped my sampler (6 concurrent loops, 11:48:40–11:54:31Z) and my §F fetches (11:54:55–11:57:05Z). I can't rule out that my probe load contributed.

## 3. Incident forensics (2026-10-05)
| ID | window UTC | (a) logs --no-tail | (b) --start/--end | (c) LogShipper/drain | (d) logs API w/ flyctl token | status |
|---|---|---|---|---|---|---|
| L2-INC-A-001 | 08:29–08:55 | earliest line in any buffer = 2026-10-06T04:38:56Z (current = 11:33:11Z) → 0 overlap | unsupported (`unknown flag: --start`) | none found: `flyctl apps list` shows only subnet-dashboard (no log-shipper app), single personal org; `git grep` @pin for log-shipper/logtail/betterstack/axiom/papertrail/datadog/NATS in fly.toml/*.yml/*.toml/Dockerfile/*.md = 0 hits | **BLOCKED by policy**: it would require extracting the token from ~/.fly/config.yml or `flyctl auth token` to mint my own API calls. Not attempted | **NOT_OBSERVABLE** |
| L2-INC-B-001 | 11:41:30–11:47:23 | same, 0 overlap | same | same | same | **NOT_OBSERVABLE** |
| L2-INC-C-001 | 11:44–11:54 (center 11:49:15) | same, 0 overlap | same | same | same | **NOT_OBSERVABLE** |
inc-a.txt / inc-b.txt / inc-c.txt contain 0 lines (header only). I can't answer the root-stall, recycle-trigger, or /static/* behavior questions from logs. The prior static work stands (evidence/l2-inc-phase2…: InstantBailout allowlist; GHA 37283988892 0-byte /health timeouts @08:43Z). **Analogy only, not evidence for 10-05:** today's buffer shows the same family of symptoms (stall guard strike, resolver cycle_timeout, health flaps; §2/§6). Note that the 10-05 INC-B/C times (11:41–11:54Z) are the same clock time as today's 11:42–11:55Z stall/flap lines. That is suggestive of a daily-scheduled heavy job, but UNPROVEN.

## 4. Carried-over findings (full table: findings-c.md)
- **A TaoStats 404**: one burst of 3 lines at 04:38:56Z; absent from both current buffers. Still firing: **unknown**. Code: fetchers/taostats_client.py:113,315.
- **B Cold-cache 10.5%**: 04:49:06Z `10.5% (count=32)` → 11:36:53Z and 11:54:27Z `10.4% (count=32)`. Still firing: **yes**. Emitted once per resolver run (internal/council/resolver.py:1385-1398). The count is frozen at 32 while the denominator grows, so no new price_data_unavailable retirements, just a stale numerator.
- **C Telegram 403** `bot is not a member of the channel chat`: 04:39:43Z, 04:49:44Z (10m01s apart), 11:55:10Z. Still firing: **yes**. Code: internal/message_intel/trend_alert.py:179. The fix is ops (re-add the bot to the channel or correct the chat_id), not code.
- **D subnet_universe shrink 168→166**: fires at 04:39:01, 04:44:32, 04:50:02, 04:55:32 (5m30s cadence = REFRESH_INTERVAL_SECONDS=300 + ~30s probe budget), then 11:36:55, 11:42:58, 11:51:33. Still firing: **yes**. All 7 of 7 fires say `168 -> 166`, across two machine restarts (10:40Z, 11:12Z).
  - **Recover vs locked: LOCKED.** The *served* universe stays 168 (the blocked path republishes the 168 LKG and persists it, subnet_universe.py:686-702; WS5 /api/subnets total=168 @03:36Z). Every *build* produces 166, and nothing ever logs a successful 168 build or a 166 publish.
  - **Two dropped netuids: UNKNOWN.** The log format (`%d -> %d`, subnet_universe.py:688-691) prints counts only, never ids. PR-branch evidence (ws5 closure/live-probes, open-questions-closure O8) gives totals (168) but no id list. There is no subnet_universe*.json anywhere on the box. Identifying them requires a read of prod `data/subnet_universe.json` (validity_map entries with `validity:"negative"`) via `fly ssh console`, or a diff of `/api/subnets` ids vs TaoMarketCap. Both are outside this task's allowed actions, so I didn't do them.
  - **Issue → code → root cause (confidence MEDIUM, static + log-consistent):** `_compute_membership` (subnet_universe.py:304-317) keeps every prior member unless `_eligible_for_removal` (negative ≥48h, :310). So a build of 166 means 2 prior members are negative past the 48h grace (or are present in `netuids` but missing from `validity_map`). `_shrink_allowed` (:234-247) then returns False at **:238 `if built.refresh_incomplete: return False`** *before* it checks grace eligibility. `refresh_incomplete` is almost always True because the probe pass covers up to 200 netuids under a 30s budget (:487, :264). The blocked branch copies the old validity_map (:698), so the stale-negative entries are never rewritten. Result: a permanent 166-build / 168-publish loop every ~5.5 min. That loop also keeps the universe `status="degraded"`.
  - **Proposed fix (pointer only):** in `_shrink_allowed` (:238), allow the shrink when `removed` ⊆ grace-eligible entries even if `refresh_incomplete`. Also add the removed netuid list to the warning at :688 (`sorted(set(prior)-set(built))`) so the next fire names them.

## 5. Endpoint freshness sampler (sampler.csv, sampler-summary.md)
Window **2026-10-06T11:48:40Z → 11:54:31Z (5m51s; 04:48:40–04:54:31 AZ)**. One thread per endpoint, 20s client timeout, 12s sleep between requests, 110 rows. A first sequential attempt (11:46:18–11:47:52Z, 8 rows, kept as sampler-v1-sequential-aborted.csv) had /version and daily-pick/learning-health timing out at 20s. I stopped it because it couldn't hit the 10–15s cadence.
| endpoint | n | statuses | min / median / max ms |
|---|---|---|---|
| /api/pump-alerts | 14 | 200×10, timeout×4 | 1603 / 10287 / 20154 |
| /api/daily-pick | 14 | 200×10 (4 of those `status:"timeout"` "pick handler busy"), timeout×4 | 1268 / 11554 / 20385 |
| /api/learning/health | 13 | 200×6 (all `status:"degraded"`, source "refreshing"), timeout×7 | 3750 / 20030 / 20074 |
| /version | 24 | 200×24 | 315 / 1690 / 9440 |
| /health | 23 | 200×23 | 224 / 1905 / 9218 |
| / | 22 | 200×22 | 503 / 2381 / 8737 |
- daily-pick payload `timestamp_utc 2026-10-06T11:37:08Z`, `action HOLD`, `reason "daily pick tick timed out after 90s"`, `scheduler_hold:true`. Data age was **691s → 986s** across the window (it never refreshed). Log: `11:37:07Z daily pick tick timed out after 90s (worker abandoned)`.
- pump-alerts: 200 bodies were `status:"empty", count 0, exit_count 2` (netuid 112). The v1 pass saw `status:"timeout" "Pump desk busy — retry shortly."`. There were 4 client timeouts at 20s, and server-side responses ran ~15s+. **No 422, no 403, no `handler_stale` seen.**
- Even the InstantBailout paths (/health, /version) reached 9.2–9.4s, which points to process/CPU starvation rather than slow handlers.
- **Verdict: STALE / degraded.** Data endpoints aren't 1s-fresh: daily-pick is 11–16 min old, learning-health times out 54% of the time, and pump-alerts is empty or timing out. Liveness endpoints were 100% 200 but with multi-second tails.

## 6. Resolver drift (resolver-evidence.txt)
Raw receipts (union of 3 buffers, 298 lines):
- `11:42:22Z resolver lifecycle event=timeout first=False duration_ms=503520.9 error=cycle_timeout_360s` → that tick started ≈11:33:58.6Z and overran the 360s timeout (fly.toml:48 RESOLVER_CYCLE_TIMEOUT_SECONDS=360) by 143.5s.
- `11:44:29Z outcome watchdog: heartbeat stale >420s — restarting loop`
- `11:44:42Z loop stall guard: resolver revive attempt -> {'revived': False, 'reason': 'tick_in_progress', … 'age_before': 3597.285253}` → last recorded resolver tick ≈ **10:44:45Z** (59.95 min earlier).
- `11:44:46Z loop stall guard: snapshot STALE (age=6826s, threshold=5400s, strike=1/2)` → last score snapshot ≈ 09:51:00Z.
- Resolver-run completion markers (cold-cache line, resolver.py:1392): 04:49:06Z, 11:36:53Z, 11:54:27Z. Interval 11:36:53→11:54:27 = **17m34s**.
- **The 15m → ~82.6m stretch is NOT CONFIRMED.** There is only 1 `resolver lifecycle` line and 0 `180s` lines in any buffer, so no pair of tick timestamps 82.6m apart exists. The largest log-derived gap is the 59.95-min tick age at 11:44:42Z.
- Where it stalls (log + code): the body does its work (writes at 11:36:53Z) but the tick isn't recorded as a success because it overruns cycle_timeout. Liveness age keeps growing, and `revive` refuses while `_cycle_lock` is held (resolver_scheduler.py:1350-1357 `tick_in_progress`). After a timeout, next_interval is forced to 2 min (:651-653); otherwise backoff = 15·2^n min capped at 240 (:645-649; 1→30, 2→60, 3→120).
- "Recovery after 3 consecutive failures": no log receipt. Code shows the stall guard kills the process on strike 2 of 2 (loop_stall_guard.py:65, 200-217 `os._exit(1)`, 240s interval) and backoff resets on the first ok (:641-643). Strike 2 would have landed around 11:48:46Z, which falls in the uncaptured gap 11:46:16–11:51:08Z, and no new machine event followed. The 31m53s spacing of the 137 exits (10:40:49 → 11:12:42Z) fits boot grace 1500s + 2×240s ≈ 33 min. That's a HYPOTHESIS, and exit code 137 ≠ `os._exit(1)`.

## 7. Signal cross-check @ 2026-10-06T11:54:55Z–11:57:05Z (signals/)
| endpoint | result |
|---|---|
| /api/council | 200 in 10.0s: `{"status":"degraded","subnets":[],"judges":[],"meta":{"count":0,"source":"busy","updated_at":"2026-10-06T11:55:03Z"}}` |
| /api/signals, /api/daily-pick, /api/whales/flow-signals, /api/top-picks | curl exit 28, 0 bytes at 30s |
| /api/daily-pick (sampler, 11:53:35Z) | HOLD, pick null, candidate null |
| row | verdict |
|---|---|
| SN21 AdTAO LONG 62.16 (52.4%); council bearish → HOLD on SN30 | NOT_OBSERVABLE (council empty/busy) |
| SN78 Vocence LONG 99.17 / ASSET DOWNGRADE | NOT_OBSERVABLE |
| SN105 Beam LONG 65.98 (0.53) | NOT_OBSERVABLE |
| SN118 Ditto LONG 66.35 (0.5345) | NOT_OBSERVABLE |
| Watchlist SN26/92/94/109/Vidaio + whale flow | NOT_OBSERVABLE (flow-signals timed out) |
| Hard rule: no LONG on downgraded (SN78, Trishool, Vidaio) | **PASS (vacuous)**: the only observable live call (daily-pick) is HOLD with pick=null; no endpoint returned any LONG |

## 8. What I could not prove
1. Fly-proxy origin of the 04:38–04:56Z 502s: no proxy lines, so routing/proxy is only the leading hypothesis.
2. Anything in L2-INC-A/B/C (2026-10-05): the buffer is 100 lines (~10–20 min). `--start` is unsupported. There is no drain. The logs-API/GraphQL path was skipped because it needs token extraction (policy). Sentry (`sentry_release` in /version) may have 10-05 events but needs separate access.
3. **The two netuids dropped in 168→166.** Next step, needs approval: `fly ssh console -a subnet-dashboard -C "python3 -c 'import json;d=json.load(open(\"data/subnet_universe.json\"));print({k:v for k,v in d[\"validity_map\"].items() if v.get(\"validity\")!=\"positive\"})'"` (read-only, but it executes in prod), or a single `/api/subnets` fetch diffed against TMC.
4. The 82.6m resolver stretch and the "3 consecutive failures" recovery (no timestamps in the buffers).
5. Signal rows: the council was busy/empty and the other signal endpoints timed out.
6. Cause of the exit-137 restarts (10:40:49Z, 11:12:42Z). flyctl shows only 5 events, and the Machines events API wasn't used (token).
7. Whether my sampler/probes contributed to the 11:51–11:55Z health-check flaps.
