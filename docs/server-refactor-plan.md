# Server.py refactor plan

This plan splits `server.py` into domain modules under `internal/` and fixes the bugs found on the way. It is for the operator who approves each PR and for the agent that runs it.
`server.py` has 3,489 lines, 107 functions, 31 routes, and 49 module globals. 158 test files and 17 production modules import it.
The program enforces one rule. Code moves with every caller and every test patch in the same PR, and `server.py` keeps no re-export.
The PRs run in order as one stack, R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12.
R0 to R9 change structure only. R10 and R11 change behavior and wait for operator review.
`server:app` stays the only entrypoint, as the single-foundation rule in `AGENTS.md` requires.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. Line numbers in this plan come from commit `8cb247e` and drift as the #1578 stack lands. Find code by symbol name, and rerun `scripts/server_inventory.py` for current lines. The body is a how-to. The appendices explain and record.

The program runs `playbooks/autopilot-stack.md` from the poteto-mode skill. The agent builds and verifies the stack. The operator lands every PR, and R10 and R11 stop at merge-ready for review.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] Confirm that #1591 has landed and that #1186 and #1330 are closed. Appendix C records why.
- [ ] Read these from trunk at program start. Re-read them at every tick.
  - [ ] `git show origin/main:AGENTS.md`
  - [ ] `git show origin/main:docs/server-refactor-plan.md`
  - [ ] `git show origin/main:cursor-agents-communication/board.md`
  - [ ] `git show origin/main:.cursor/rules/ponytail.mdc`
  - [ ] The skill files `playbooks/autopilot-stack.md`, `playbooks/autopilot-full.md`, `playbooks/opening-a-pr.md`, and `swarm/SKILL.md`. They live in the agent's skills directory, not in this repo.
- [ ] On the operator's go, arm the audit tick as `/loop 1h` with the tick prompt below. Never leave the cadence to memory.
- [ ] Use this tick prompt, verbatim. "Re-read the execution playbook and this plan. Audit the operation against them and fix drift in this tick. Probe every active lane and judge progress by side effects only. Stand down a stuck lane and dispatch its replacement now. Then post a short status message to the operator in chat only when the audit found a tracked change that no earlier status message reported. Name every such change and nothing else. If the audit found none, end the turn with no reply text. Either way, log this tick's row in the decision trail."
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR, one at a time. `AGENTS.md` forbids concurrent edits to the working tree.
- [ ] Follow this dependency graph. Each PR branches from its parent's branch.
  - [ ] R0 is first and branches from `main`.
  - [ ] R1 to R12 each follow the PR before them.
- [ ] Hold the file boundaries. R0 to R9 change no response body, status code, or header, except the one fix that R5 names. R10 and R11 edit only the files their sections list.
- [ ] Post on the agent board before R1, R2, R3, R6, R8, and R11. They edit files in packages that Agent A and Agent B own.
- [ ] Stop a move PR that cannot keep `tests/test_server_golden.py` unchanged. Revert it, split it, and report the body that changed. Do not edit a stored golden file in R1 to R9, except the one `/api/stats` case that R5 names.
- [ ] Hold the review gate. R10 and R11 change an interaction. They wait for the operator's review in chat with screenshots and a video before merge.

### PR mechanics, for every PR

- [ ] Use the GitHub MCP tools for every PR operation, as this environment's rules require.
- [ ] Open the PR ready, never draft. A stack child targets its parent branch.
- [ ] Apply the operator's standing review rule of 2026-11-16 to every PR. Run its eleven skills, which are `code-review`, `poteto-mode`, and the nine principle skills it names. A Sonnet 5.5 subagent review is part of the gate. Replit posts its review as a PR comment, and Ditto reviews after each push.
- [ ] Verify locally with `DATA_DIR` set to a temporary copy. A test run that writes the tracked `data/` directory trips the stop hook.
- [ ] Narrow a broad `except Exception` only by this rule. Where the try body does I/O or parsing, narrow to those failures, such as `OSError`, `ValueError`, `JSONDecodeError`, timeouts, and the HTTP client's errors. Where the try body is pure internal code, delete the `try` and let the error reach the boundary, because a `KeyError` or `TypeError` there is a bug that someone should see. Keep a broad handler only at a boundary (a route handler, a thread entry, or a boot hook) and log it with `logger.exception` so the traceback survives. Do not change a handler in a move PR unless that PR already changes the moved lines. The count in `tests/test_server_budget.py` only goes down.
- [ ] Run `pytest tests/test_endpoint_contract.py` once before the PR-facing push. Push with hooks on.
- [ ] Rebase onto current trunk before the code-ready report. Rebase again only on a conflict with trunk or on a CI failure that comes from trunk.
- [ ] Re-run `python scripts/server_inventory.py` after every rebase. An open PR that added a `server` import or patch shows up as a raised count.

### Verdict and merge, for every PR

- [ ] A full swarm runs once, at the code-ready head. It has one gates lane, the ten live lanes from the PR's **Verify, live** block, the perf lane, and two audit lanes that read the diff and distrust the PR body.
- [ ] Clean only when every lane is `PASS`. Findings go back to the owner. A new head gets a fresh verdict.
- [ ] The root appends each clean PR to the stack. The operator lands the stack bottom-up and triggers the Fly deploy by `workflow_dispatch`.

### Deploy checkpoints

- [ ] The operator lands and deploys the stack in four batches, R0 to R1, R2 to R4, R5 to R9, and R10 to R12. A batch waits until the batch before it has run in production for 24 hours.
- [ ] After each deploy, confirm that `GET /version` reports the landed SHA.
- [ ] Watch four signals for 24 hours. They are the `/health` reply time, the count of 5xx replies in `/metrics`, new issues in Sentry, and the liveness report from `GET /api/ops/live`.
- [ ] If any signal is worse than before the deploy, the operator redeploys the previous SHA through the Fly workflow. The owner then reproduces the fault before the batch lands again.

### Boot recipe, for every live lane

Each live lane runs at the PR head on its own checkout. No control skill is installed for this repo, so lanes drive the app with `curl` and with the preinstalled Playwright Chromium.

- [ ] `git fetch origin <head-branch> && git checkout <head SHA>`.
- [ ] `python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest httpx`.
- [ ] `PORT=5000 .venv/bin/python server.py`, then wait until `curl -s localhost:5000/health` prints `OK`.
- [ ] Send input only through HTTP requests and Chromium page loads. Read state only from responses, the server log, and `git status`.
- [ ] Save every artifact to `/tmp/swarm-<pr-id>/worker-<n>/<slug>` and return the paths with the report.

## Pin the contract and make the tests hermetic (R0)

**Depends on.** None.

**Files.**

- [ ] Create `scripts/route_manifest.py`.
- [ ] Create `scripts/perf_probe.py`.
- [ ] Create `tests/test_route_manifest.py` and `tests/fixtures/route_manifest.json`.
- [ ] Create `tests/test_server_golden.py` and `tests/fixtures/server_golden/`.
- [ ] Create `tests/test_server_budget.py`.
- [ ] Edit `tests/conftest.py`.

**Build.**

- [ ] `scripts/route_manifest.py` writes every route as a method and path pair, the mounts (`/static` and `/ws/signals`), and the middleware classes in the order of `app.user_middleware`. The test compares the route pairs as a set and the middleware order exactly. Route order does not constrain the moves, because no route defined in `server.py` overlaps another, so the script stores no endpoint module and no route order.
- [ ] Add a `frozen_world` fixture. It stubs the subnet feed with 5 fixed rows, freezes the clock, sets `TZ` to `UTC` and a fixed locale, points `DATA_DIR` at a seeded temporary copy, and blocks the network.
- [ ] `tests/test_server_golden.py` requests every route that `server.py` defines inside `frozen_world` and compares the whole body and four headers with a stored file. The headers are `Cache-Control`, `Access-Control-Allow-Origin`, `X-Frame-Options`, and whether `Server-Timing` is present. One case is a write that `check_write_auth` denies, so that a reply produced by a middleware is pinned too. It stores the HTML of `/` in the cold, emergency, and warm state. A move PR must leave every stored file unchanged.
- [ ] Know what the stored files capture. `internal/instant_bailout.py:129` to `164` answers `GET /`, `/health`, `/api/health`, `/version`, and `/api/ops/live` before FastAPI runs. The stored bodies for those paths are the wrapper output. Add one case per path that calls the inner FastAPI app, so that the handlers the plan moves are pinned too.
- [ ] Render `index.html` once with Jinja `StrictUndefined` and store the list of context keys the template reads. The app uses the default `Undefined`, which prints a missing key as an empty string.
- [ ] `tests/test_server_budget.py` holds eight numbers that later PRs may lower and never raise. Four of them count across `server.py` and every module this plan creates. They are 135 function-level imports, 73 `except Exception` handlers, 29 `os.environ.get` reads, and 17 imports of a private name from another package. A fifth counts every `server.<name>` or `srv.<name>` reference in `tests/` other than `app`, which is 231 today. Of those, 107 read or write a cache, lock, or flag directly. The other three follow. Take the starting numbers from `scripts/server_inventory.py` after #1591 lands. On `8cb247e` they are 3489 lines in `server.py`, 21 lines outside `tests/` that import `server`, and 81 test sites that patch a `server` attribute. #1591 adds 5 patch sites.
- [ ] Record in the fixture docstring why the contract test wrote files. `GET /api/signals` regenerates signals inline when the store is stale, at `internal/signals/routes.py:196`. The fixture contains the write. This PR does not change the route.
- [ ] Add an autouse fixture in `tests/conftest.py` that copies `data/` and `config/` to `tmp_path`, sets `DATA_DIR`, and changes the working directory, so that no test writes a tracked file.
- [ ] List every writer the contract test reaches that ignores `DATA_DIR`. Route each one through `internal/data_volume.py`.
- [ ] Download the `pytest-junit` artifact that `.github/workflows/full-suite-junit.yml` records for trunk. Store its failing test ids as `artifacts/server-refactor/baseline-failures.txt`. Every later PR compares its own artifact with this list.

**You see.**

- [ ] `pytest tests/test_endpoint_contract.py` prints `149 passed` and `git status --short` prints nothing afterwards. Today the same run modifies 6 files under `data/`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_route_manifest.py` gains the manifest equality case. Run `pytest tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py tests/test_endpoint_contract.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R0/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R0/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R0/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R0/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R0/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R0/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R0/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R0/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R0/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Run the full `pytest` suite twice in a clean checkout. Save `/tmp/swarm-R0/worker-10/git-status.txt`. Pass when `git status --short` is empty after both runs and the failure list equals the trunk failure list.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R0/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R0 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Delete the unreachable homepage build and other dead code (R1)

**Depends on.** R0.

**Files.**

- [ ] Edit `server.py`.
- [ ] Edit `tests/test_fast_shell_context.py` and the other tests that `python scripts/server_inventory.py` lists for the deleted names.

**Build.**

- [ ] Delete `_resolve_index_context`, `_build_index_context`, `_degraded_index_context`, `_home_hero_context`, `_shell_pump_and_picks`, `_safe_brain_letter_context`, `_safe_mindmap_graph_context`, `_pump_alerts_context`, `_simileads_context`, `_pick_netuid_from_daily_payload`, and `_DEGRADED_INDEX_CACHE` from `server.py`. No production code calls the first one, and the rest are reachable only through it.
- [ ] Delete `_subnets_for_spotlight_lite`, `_enrich_daily_pick_payload`, and the `safe_list` Jinja filter. Nothing in production or in `templates/` uses them.
- [ ] Reduce `_message_intel_shell_context` to its skeleton. After the deletions every caller passes `fast=True`.
- [ ] Delete `build_learning_dashboard_context` and `_pick_sections` from `internal/learning/dashboard_context.py`. Their only callers are the functions deleted above. This removes the page-render path that scored every subnet and wrote predictions, which #1330 tried to make read-only.
- [ ] Delete the unused import `populate_author_reliability` from `server.py`. Leave `get_or_create_today_pick` where it is. It sits inside the `_PICKS_ENGINE` guard, and removing it would change when that flag is true.
- [ ] Delete the 9 panel helpers in `internal/learning/dashboard_context.py` that only `build_learning_dashboard_context` calls, about 150 lines. Confirm with a caller search that nothing else uses them.
- [ ] Delete the tests that exercise only the deleted functions. Remove the 6 test patches of `server.get_or_create_today_pick`, which patch a name that `server.py` never calls, and keep each test only if it still fails when its behavior breaks.
- [ ] Lower the line budget in `tests/test_server_budget.py` to the new count.

**You see.**

- [ ] `wc -l server.py` prints about 3050. `python scripts/server_inventory.py . /tmp/inv.json` prints `functions 94` or fewer.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_server_budget.py` gains the lowered line budget. Run `pytest tests/test_endpoint_contract.py tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R1/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R1/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R1/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R1/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R1/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R1/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R1/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R1/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R1/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Request `/` with `HOMEPAGE_BUILD_TIMEOUT=1` and a blocked network. Save `/tmp/swarm-R1/worker-10/home-degraded.png`. Pass when the page still contains `tribunal-hero`, the same as trunk.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R1/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R1 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move the subnet source and market context out of server.py (R2)

**Depends on.** R1.

**Files.**

- [ ] Create `tests/test_import_layers.py`.
- [ ] Create `internal/subnets/source.py`.
- [ ] Create `internal/subnets/registry.py`.
- [ ] Create `internal/council/market_context.py`.
- [ ] Edit `server.py`.
- [ ] Edit `internal/analytics/market_drivers.py`, `internal/analytics/report.py`, `internal/council/pick_audit_scheduler.py`, `internal/council/pick_scheduler.py`, `internal/council/score_snapshots.py`, `internal/dev_radar/service.py`, `internal/indicators/routes.py`, `internal/letter/brain_letter.py`, `internal/message_intel/routes.py`, `internal/oracle/routes.py`, `internal/share_pages/search.py`, `internal/simivision/chat_service.py`, `internal/simivision/graded_context.py`, and `internal/council/build_seed_snapshot.py`.
- [ ] Edit every test that patches the moved names.

**Build.**

- [ ] Move `_get_subnets_with_source`, `_get_subnets_hydrate`, and `_STATIC_SUBNETS` to `internal/subnets/source.py` as `get_subnets_with_source`, `get_subnets_hydrate`, and `STATIC_SUBNETS`.
- [ ] Move `_normalize_registry_subnet` to `internal/subnets/registry.py`.
- [ ] Move `_market_mood_proxy`, `_market_context_with_weights`, and `_safe_macro_overlay` to `internal/council/market_context.py`.
- [ ] Change the 13 production modules to import from the new modules. Change `server.py` to import the same names.
- [ ] `internal/council/build_seed_snapshot.py:36` patches `server._get_subnets_hydrate` in production code. Point that patch at `internal.subnets.source.get_subnets_hydrate` and delete its `import server`. Then run `git grep -nE "patch.object.server|setattr.server" -- internal scripts` and repoint anything else it finds.
- [ ] Create `tests/test_import_layers.py` with the rules that already hold. A module under `internal/` may import `server` only if it is on an allowlist, and `internal.web` imports no feature package. R2 and R3 remove entries from the allowlist, so layering is enforced while modules appear and not only at the end.
- [ ] Move the weights import guard at `server.py:189` to `196` into `internal/council/market_context.py` unchanged. `_market_context_with_weights` depends on its fallback.
- [ ] Move `load_data` to `internal/subnets/registry.py` unchanged. Do not replace it with `safe_read_json`, which hides a corrupt file that `load_data` reports.
- [ ] Repoint the test patches of `_get_subnets_with_source` (10), `_market_context_with_weights` (6), `load_data` (4), and `_get_subnets_hydrate` (3) to the module that now calls the function. Leave no re-export in `server.py` for tests to patch.
- [ ] Lower the import budget and the patch budget in `tests/test_server_budget.py`.

**You see.**

- [ ] `git grep -nE "from server import" -- internal` prints only the lines for `_safe_simivision_payload` and `import server as srv`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Add `tests/test_subnet_source.py` with one case per fallback branch of `get_subnets_with_source`. Run `pytest tests/test_subnet_source.py tests/test_endpoint_contract.py tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R2/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R2/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R2/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R2/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R2/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R2/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R2/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R2/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R2/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Run `python -X importtime -c "import internal.council.pick_scheduler"` and call its subnet loader. Save `/tmp/swarm-R2/worker-10/scheduler-imports.txt`. Pass when `server` is absent from `sys.modules` after the call.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R2/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R2 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move pick and SimiVision logic out of server.py (R3)

**Depends on.** R2.

**Files.**

- [ ] Create `internal/council/hour_picks.py`.
- [ ] Create `internal/council/daily_pick_read.py`.
- [ ] Create `internal/council/top_picks_read.py`.
- [ ] Create `internal/simivision/board.py`.
- [ ] Edit `internal/request_executor.py`.
- [ ] Edit `server.py`, `internal/learning/dashboard_context.py`, and `internal/learning/dpick_spotlight.py`.
- [ ] Edit every test that patches the moved names.

**Build.**

- [ ] Move `_ordered_hour_picks`, `_build_hour_pick_payload`, `_highest_emission_pick`, `_record_pick_in_learning_loop`, and `_subnet_for_pick` to `internal/council/hour_picks.py`.
- [ ] Move `_enrich_daily_pick_payload_lite`, `_attach_daily_pick_meta`, the two hold builders, `_hydrate_daily_pick_lite`, `_coalesce_daily_pick_flight`, `_daily_pick_weighed_shortlist`, and their locks to `internal/council/daily_pick_read.py`.
- [ ] Move `_read_shell_daily_pick` and `_today_daily_pick_for_board` to `internal/council/daily_pick_read.py` in this PR. `_simivision_build_inner` calls them, and leaving them for R7 would make `internal/simivision/board.py` import `server`.
- [ ] Move the `_PICKS_ENGINE` import guard at `server.py:175` to `187` into `internal/council/hour_picks.py` with its import list unchanged. The flag must turn false under the same failures as today.
- [ ] Move the top-picks builders and cache to `internal/council/top_picks_read.py`.
- [ ] Move `_safe_simivision_payload`, `_simivision_build_inner`, `_simivision_weighing_rows_cached`, `_kick_simivision_background_refresh`, `_build_simivision_cached`, and the SimiVision cache to `internal/simivision/board.py`.
- [ ] Move `_to_thread_timeout`, `_DASHBOARD_EXECUTOR`, and `_PICK_READ_EXECUTOR` into `internal/request_executor.py`. Name the moved helper `dashboard_to_thread_timeout` and keep `_DASHBOARD_EXECUTOR` as its default pool. The file already has a `to_thread_timeout` with a different default pool, so the two must not merge.
- [ ] Move the two `atexit.register` calls at `server.py:588` and `691` with their pools. Without them the pool threads are joined at interpreter exit, which hung CI before.
- [ ] Repoint the remaining importers and test patches. The route handlers stay in `server.py` and call the new modules.
- [ ] Lower the three budgets in `tests/test_server_budget.py`. The import budget reaches the 2 lines in `asgi_entry.py` and `scripts/restless_openapi.py`.

**You see.**

- [ ] `git grep -nE "from server import|import server" -- internal` prints only the comment in `internal/live_subnets_fetch_child.py`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Add one test file per new module that covers the cold, warm, and busy branch of its cache. Run those files plus `pytest tests/test_endpoint_contract.py tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R3/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R3/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R3/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R3/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R3/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R3/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R3/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R3/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R3/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Hold `_get_subnets_with_source` for 10 seconds with a patch and request `/api/top-pick/hour` and `/api/daily-pick`. Save `/tmp/swarm-R3/worker-10/timeouts.json`. Pass when both answer inside their handler timeout with the same payload shape as trunk.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R3/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R3 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Replace the five hand-written caches with one cache type (R4)

**Depends on.** R3.

**Files.**

- [ ] Create `internal/swr_cache.py`.
- [ ] Create `tests/test_swr_cache.py`.
- [ ] Edit `internal/simivision/board.py`, `internal/council/top_picks_read.py`, `internal/council/hour_picks.py`, `server.py`.

**Build.**

- [ ] Write a characterization test for each of the five caches before any change. Each test records what a fresh, stale, cold, and busy read returns today. Appendix E lists how the five differ.
- [ ] Run the **architect** skill on the shape of `SwrCache` before coding. The type owns one payload, its age, one build lock, and one background-refresh flag, and a read returns the payload with a freshness of `fresh`, `stale`, or `miss`.
- [ ] Replace the subnets, SimiVision, top-picks, hour-pick, and pump-alerts caches, one commit per cache, with the characterization test green after each commit.
- [ ] Delete the 20 module globals that the five caches used.
- [ ] Every `SwrCache` adds itself to one module-level list, and `reset_all()` empties them all. An autouse fixture in `tests/conftest.py` calls it, so that one test cannot leave a payload for the next.

**You see.**

- [ ] `git grep -n _BG_REFRESHING -- server.py internal` prints nothing. The five characterization tests pass unchanged.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_swr_cache.py` gains fresh, stale, miss, busy, failed-build, and non-cacheable-payload cases with an injected clock. Run `pytest tests/test_swr_cache.py` plus the five characterization files and the four pin files.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R4/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R4/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R4/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R4/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R4/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R4/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R4/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R4/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R4/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Send 40 concurrent cold requests to `/api/pump-alerts` with the build patched to count calls. Save `/tmp/swarm-R4/worker-10/pump-builds.txt`. Pass when the build count is no higher than the trunk count.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R4/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R4 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move the subnet catalog routes into internal/subnets (R5)

**Depends on.** R4.

**Files.**

- [ ] Create `internal/subnets/routes.py`.
- [ ] Create `internal/subnets/catalog.py`.
- [ ] Create `internal/subnets/stats.py`.
- [ ] Edit `server.py`.
- [ ] Edit `tests/test_endpoint_contract.py` only if a comment names the old location.

**Build.**

- [ ] Move `GET /api/registry`, `/api/subnets`, `/api/subnet/{subnet_id}`, `/api/subnet/{subnet_id}/pool`, `/api/summary`, and `/api/stats` to a `subnets_router` in `internal/subnets/routes.py`. Route order is free here, because no route in `server.py` overlaps another route.
- [ ] Move `_list_subnets_base_rows`, `_apply_subnets_query`, `_null_unfetched_metrics`, `_list_subnets_registry_fallback`, `_tag_subnet_row`, and `_consensus_map` to `internal/subnets/catalog.py`. The two functions that build rows share one row builder.
- [ ] Put the status counts and totals that `get_summary` and `get_stats` both compute into one pure function in `internal/subnets/stats.py`. The two routes rank and shape their lists differently, so each keeps its own ranking. Use the `None`-safe access from `get_summary`. This fixes bug B6 in Appendix F, so add its regression test in this PR.

**You see.**

- [ ] `grep -c "@app.get" server.py` drops by 6. `GET /api/stats` returns 200 for a row whose `staking_data` is `None`, where trunk returns 500.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Add `tests/test_subnet_stats.py` with the `staking_data` regression case and one case per ranking. Run it with the four pin files.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R5/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R5/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R5/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R5/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R5/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R5/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R5/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R5/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R5/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Request `/api/subnets` with `sort`, `order`, `limit`, `offset`, `fields`, and `status` in 12 combinations at trunk and head. Save `/tmp/swarm-R5/worker-10/subnets-matrix.json`. Pass when all 12 bodies are equal after removing `generated_at`.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R5/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R5 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move the pick and SimiVision routes into their packages (R6)

**Depends on.** R5.

**Files.**

- [ ] Create `internal/council/picks_routes.py`.
- [ ] Edit `internal/simivision/routes.py`.
- [ ] Edit `server.py`.

**Build.**

- [ ] Move `GET /api/daily-pick`, `/api/daily-pick/weighed`, `/api/top-picks`, `/api/top-pick/day`, `/api/top-pick/hour`, and `/api/pick-explain/{netuid}` to a `picks_router` in `internal/council/picks_routes.py`.
- [ ] Move `GET /api/simivision` to the existing router in `internal/simivision/routes.py`.
- [ ] Post the import-line change on the agent board first. `internal/council/` belongs to Agent A.

**You see.**

- [ ] `grep -c "@app.get" server.py` drops by 7.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] The pin files cover the move. Run `pytest tests/test_endpoint_contract.py tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py tests/test_api_handler_timeouts.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R6/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R6/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R6/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R6/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R6/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R6/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R6/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R6/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R6/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Send 30 concurrent `GET /api/daily-pick` requests through `asyncio.gather` in one event loop. Save `/tmp/swarm-R6/worker-10/gather-burst.json`. Pass when all 30 resolve in under 2 seconds, which is the deadlock case the `wrap_future` comment guards.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R6/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R6 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move the homepage into internal/home (R7)

**Depends on.** R6.

**Files.**

- [ ] Create `internal/web/templating.py`.
- [ ] Create `internal/home/shell.py`.
- [ ] Create `internal/home/context.py`.
- [ ] Create `internal/home/routes.py`.
- [ ] Edit `server.py` and the tests that patch homepage names.

**Build.**

- [ ] Move the Jinja environment, its filters, and its globals to `internal/web/templating.py`.
- [ ] Put the homepage cache in one `HomeShell` object in `internal/home/shell.py`. It replaces `_HOMEPAGE_HTML_CACHE`, `_EMERGENCY_HOME_HTML`, `_HOMEPAGE_WARM_LOCK`, `_HOMEPAGE_WARMING`, and `_HOMEPAGE_RENDER_THREAD`, and it has three states, `cold`, `emergency`, and `warm`.
- [ ] Build the homepage context in one function in `internal/home/context.py` that takes a tier. The ultra-minimal tier is the minimal tier without file reads. The three copies of the `signal_summary` and `pump_alerts` placeholders become one constant each.
- [ ] Move `GET /` to `internal/home/routes.py`. Pass `HomeShell` methods to `wrap_instant_bailout` in `server.py`.
- [ ] Give `HomeShell` a `reset()` and call it from the same autouse fixture as `reset_all()`. Delete the hand-written reset helpers in `tests/test_fast_shell_context.py`.
- [ ] Assert that the context builder returns every key in the stored `StrictUndefined` list, for each tier.

**You see.**

- [ ] `grep -c "global " server.py` prints 0. `/` returns the same HTML as trunk for the cold, emergency, and warm state.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Add `tests/test_home_shell.py` with one case per state change of `HomeShell`. Run it with the four pin files and `pytest tests/test_visual_upgrade_polish.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R7/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R7/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R7/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R7/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R7/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R7/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R7/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R7/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R7/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Render `/` in the cold, emergency, and warm state at trunk and head. Save `/tmp/swarm-R7/worker-10/home-states.diff`. Pass when the three HTML bodies are equal after removing timestamps.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R7/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R7 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Move the small page and feedback routes (R8)

**Depends on.** R7.

**Files.**

- [ ] Create `internal/preview/routes.py`.
- [ ] Create `internal/mindmap/soul_map_routes.py`.
- [ ] Edit `internal/pump/routes.py` and `internal/health/routes.py`.
- [ ] Edit `server.py`.

**Build.**

- [ ] Register the 6 `/preview/*` pages from one table of path, template, and context builder in `internal/preview/routes.py`.
- [ ] Move `GET /pump`, `/Pump`, and `/api/pump-alerts` to a new `pump_desk_router` in `internal/pump/routes.py`. Include it directly from `server.py`. The existing `pump_ladder_router` is included through the guarded analytics router, and these three routes have no guard today.
- [ ] Move `GET /health`, `/version`, `/robots.txt`, and `/favicon.ico` to `internal/health/routes.py`. Keep `/health` async. The bailout wrapper answers `/health`, `/version`, and `/api/health` first, so these handlers serve only a request that reaches the inner app.
- [ ] Move `GET /api/soul-map`, `/api/recommendations`, `/api/daily-rotation`, and `POST /api/mindmap/feedback` to a new `soul_map_router` in `internal/mindmap/soul_map_routes.py`. Include it directly from `server.py`. The existing mindmap router is optional and can be `None`.

**You see.**

- [ ] `grep -cE "@app\.(get|post)" server.py` prints 0.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] The pin files cover the move. Run `pytest tests/test_endpoint_contract.py tests/test_route_manifest.py tests/test_server_golden.py tests/test_server_budget.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R8/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R8/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R8/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R8/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R8/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R8/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R8/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R8/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R8/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Load all 6 `/preview/*` pages in Chromium at trunk and head. Save `/tmp/swarm-R8/worker-10/previews.png`. Pass when each pair has a pixel difference of 0.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R8/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R8 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Reduce server.py to app assembly (R9)

**Depends on.** R8.

**Files.**

- [ ] Create `internal/app/routers.py`.
- [ ] Create `internal/app/lifespan.py`.
- [ ] Create `internal/app/http_edge.py`.
- [ ] Create `internal/web/settings.py`.
- [ ] Edit `server.py`.
- [ ] Edit the tests that reference `server.templates` or `server._lifespan`.

**Build.**

- [ ] Replace the 16 guarded import blocks with one table in `internal/app/routers.py`. Each row names the module, the router attribute, and whether the router is required. One loop imports and includes them in the manifest order and logs the same warning as today for an optional router that fails.
- [ ] Move `_lifespan` and its boot helpers to `internal/app/lifespan.py`. Split it into one function for the worker boot and one for the web boot.
- [ ] Move `_CACHE_PATHS`, `_ALLOWED_ORIGINS`, `add_cors_headers`, and the write-auth middleware to `internal/app/http_edge.py`.
- [ ] Create `internal/web/settings.py` with one default per environment variable. Replace the 29 `os.environ.get` reads that started in `server.py`. The 17 that are read once at import stay module constants, and callers read them as `settings.NAME` at use, so that a test patches one place. The 12 that are read on each call become functions. Keep both defaults of `HOMEPAGE_SHELL_CACHE_SECONDS` under two names, because R10 merges them.
- [ ] Keep the request log line on the logger named `server`. A log filter outside the repo may match that name.
- [ ] Leave in `server.py` only the Sentry and logging setup, app creation, the calls that mount middleware and routers, the bailout and Restless wrappers, and `__main__`.
- [ ] Lower the line budget in `tests/test_server_budget.py` to 150.

**You see.**

- [ ] `wc -l server.py` prints 150 or fewer. `uvicorn server:app` and `uvicorn asgi_entry:app` both boot and print `lifespan_ready`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Add `tests/test_router_table.py`. One case makes an optional router fail to import and expects the app to boot without it, and one case makes a required router fail and expects the boot to raise. The required rows are the routers that R5 to R8 create, and the test requests `/pump` and `/api/soul-map` to show they survive a failed analytics import. Run it with the four pin files.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R9/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R9/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R9/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R9/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R9/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R9/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Start the app through each entrypoint in turn. They are `uvicorn server:app`, `python scripts/run_web_with_guard.py`, `sh scripts/fly_worker_entrypoint.sh`, `python server.py`, and `python scripts/restless_openapi.py`. Save `/tmp/swarm-R9/worker-7/entrypoints.log`. Pass when the first four answer `OK` on `/health` and the last exits 0.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R9/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R9/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Boot with `RUN_MODE=worker`, then with `BACKGROUND_ON_WEB=off`, then with defaults. Save `/tmp/swarm-R9/worker-10/boot-modes.log`. Pass when the set of started thread names in each mode equals the trunk set.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R9/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R9 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Fix the HTTP edge bugs (R10)

**Depends on.** R9.

**Files.**

- [ ] Edit `internal/app/http_edge.py`, `internal/app/routers.py`, `internal/council/picks_routes.py`, `internal/simivision/routes.py`, `internal/simivision/board.py`, `internal/mindmap/` router, `internal/health/routes.py`.
- [ ] Edit `static/js/cockpit_hydrate.js` and `static/js/living_focus.js` if they read the old shapes.
- [ ] Create `tests/test_http_edge_bugs.py`.

**Build.**

- [ ] Commit the failing tests first, one per bug B1 to B5 in Appendix F, copied from the probes in `scripts/server_refactor_probes.py`.
- [ ] B1. A timeout or error payload must not carry `Cache-Control: public`. The handler that builds a degraded payload sets `no-store`, and the middleware adds a public TTL only to a GET that returned 200.
- [ ] B2. Stop sending exception text to clients. Log the exception and return a fixed error code in the `error` field.
- [ ] B2 status codes. A payload the page can still use, with `status` set to `timeout`, `busy`, or `pending`, stays HTTP 200, because `fetchJson` in `static/js/cockpit_hydrate.js` throws away the body of any other status. A hard failure with no data returns 503. A bad request body on `POST /api/mindmap/feedback` returns 400.
- [ ] Define the reply states once. The standalone helper PR in `docs/roadmap-proposal.md` adds `degraded(status, body)` at `internal/web/replies.py`. This PR adds a `PayloadStatus` literal type to it, makes it set `no-store`, and replaces each hand-built timeout, busy, pending, and error reply in the moved route modules. `server.py` spells 12 status strings by hand today.
- [ ] B3. `GET /api/simivision` returns `status` and `data` in every branch, including the cold and timeout branch.
- [ ] B4. Read `HOMEPAGE_SHELL_CACHE_SECONDS` once. The public `max-age` for `/` and the shell cache age use that one value.
- [ ] B5. Report the routers that failed to import under a `routers` key in the report that `fetch_ops_live_report` builds for `GET /api/ops/live`. The bailout wrapper answers `/api/health` with a constant, so a key there would never be seen.

**You see.**

- [ ] `PYTHONPATH=. python scripts/server_refactor_probes.py` prints `no-store` on P2, the same key set twice on P5, status 400 on P6, and no exception text on P7.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_http_edge_bugs.py` gains 5 cases that fail on the parent commit and pass on the fix commit. Run it with `pytest tests/test_endpoint_contract.py tests/test_route_manifest.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `PYTHONPATH=. python scripts/server_refactor_probes.py` at trunk and at head. Save `/tmp/swarm-R10/worker-1/probes.diff`. Pass when only the P2, P5, P6, P7, and P10 lines differ and the route manifest is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R10/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R10/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R10/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R10/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` cold, warm, and with the build forced to time out. Save `/tmp/swarm-R10/worker-6/simivision-shapes.json`. Pass when all three have the keys `status` and `data`.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R10/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R10/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R10/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Load `/` in Chromium with `/api/simivision` and `/api/top-picks` forced to time out. Save `/tmp/swarm-R10/worker-10/home-timeouts.png`. Pass when the weighing room and picks panels show their busy state and the console shows zero errors.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R10/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** The operator reviews before merge.

- [ ] Copy the lane 6 and lane 10 screenshots into `artifacts/server-refactor/R10-review-shapes.png`.
- [ ] Record a 30 to 60 second video of the homepage under forced timeouts on a lane VM. Save it as `artifacts/server-refactor/R10-review.mp4`.
- [ ] Post the screenshots, the video, and the list of changed status codes in chat. Stop at merge-ready. Wait for the operator's click.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Fix the data and read-path bugs (R11)

**Depends on.** R10.

**Files.**

- [ ] Edit `internal/subnets/source.py`, `internal/subnets/stats.py`, `internal/subnets/routes.py`, `internal/council/hour_picks.py`, `internal/council/picks_routes.py`, `internal/council/pick_scheduler.py`, `internal/council/state_vector.py`, `internal/simivision/board.py`, `internal/home/routes.py`, `internal/home/shell.py`, `internal/learning/dashboard_context.py`, and `internal/mindmap/soul_map_routes.py`.
- [ ] Create `tests/test_data_integrity_bugs.py`.

**Build.**

- [ ] Commit the failing tests first, one per bug D1 to D9 in Appendix F.
- [ ] D1. Delete `STATIC_SUBNETS`. Neither recorder in `internal/learning/prediction_loop.py` checks where a row came from, so the invented rows would be stored. When the feed fails, the source returns no rows and the pick routes return their `pending` shape.
- [ ] D2. Delete the call to `_record_pick_in_learning_loop` from the hour-pick read path. `internal/council/pick_scheduler.py:203` already records the audited hour pick and its hold. Move the near-miss shadow recording and the fallback hold to the same scheduler function. This adds one `score_universe` call to each scheduler tick, so measure the tick time before and after. A GET must not write learning state.
- [ ] D3. The fault PR F2-A fixes `server.py:2802` and is already pushed. This PR does the rest. Replace `datetime.now(timezone.utc).isoformat() + "Z"` in all 3 production sites with the `.replace("+00:00", "Z")` form the file already uses elsewhere. The third site is `internal/council/state_vector.py:1313`, which writes a stored value. First show that every reader of that value parses both forms, and keep reading both.
- [ ] D4. In `GET /api/subnet/{subnet_id}`, skip a row whose `netuid` is not an integer and keep scanning.
- [ ] D5. In `POST /api/mindmap/feedback`, test `subnet_id is not None` on both lines that check it, `server.py:2373` and `2398`, so that netuid 0 is accepted once.
- [ ] D6. `GET /api/summary` and `GET /api/stats` read the subnets cache. Today each request rebuilds every row.
- [ ] D8. The fault PR F1-A fixes this and is already pushed on `fix/f1a-timeout-bound`. If it has landed, check that the sweep key `timeout_joined_by_with_block` reads 0 and do nothing else here. Otherwise `_prime_emergency_home_html` must return at its timeout. Create the executor without a `with` block and call `shutdown(wait=False)`, as `_safe_brain_letter_context` did. Today the `with` block waits for the hung render.
- [ ] D9. Also fixed by F1-A. If it has landed, skip this box. Otherwise apply the same change to `fast_shell_dashboard_context` at `internal/learning/dashboard_context.py:120`, and keep one worker in flight at a time so that repeated timeouts cannot stack threads. The second half answers the review blocker that parked #1330.
- [ ] D7. Give the homepage one code path. The bailout wrapper answers every `GET /`, so the `index` route handler is unreachable and its inline Jinja render never runs in production. Make the handler return the same `HomeShell` result the wrapper uses, and delete the inline render.

**You see.**

- [ ] `PYTHONPATH=. python scripts/server_refactor_probes.py` prints an empty `recorded` list on P8, `6 requests -> 1 full rebuilds` or fewer on P3b, and a timestamp ending in `Z` without `+00:00` on P1. P9 no longer applies.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_data_integrity_bugs.py` gains 9 cases that fail on the parent commit and pass on the fix commit. Run it with the four pin files.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `PYTHONPATH=. python scripts/server_refactor_probes.py` at trunk and at head. Save `/tmp/swarm-R11/worker-1/probes.diff`. Pass when only the P1, P3b, and P8 lines differ and the route manifest is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R11/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R11/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R11/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R11/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R11/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R11/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent cold `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R11/worker-8/health-cold-burst.txt`. Pass when every `/health` reply arrives in under 200 ms, including during the first render.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R11/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Block the subnet feed, request `/api/top-pick/hour` 10 times, then diff `data/`. Save `/tmp/swarm-R11/worker-10/data-diff.txt`. Pass when no file under the data directory changed and every response has `status` set to `pending` or `busy`.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. The standard latencies, plus p95 of `GET /api/stats` and `GET /api/summary`, and the longest event-loop stall during a cold `GET /`.
- [ ] Probe. Run `python scripts/perf_probe.py --routes /api/stats,/api/summary --loop-stall` three times at trunk and three times at head, interleaved.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R11/perf-trunk.json`.
- [ ] Rule. The PR fails when the head p95 of `/api/stats` or `/api/summary` is not lower than trunk, when the cold-render loop stall is above 50 ms, or when any standard route regresses by more than 15 percent.

**Review gate.** The operator reviews before merge.

- [ ] Copy the lane 5 and lane 10 screenshots into `artifacts/server-refactor/R11-review-picks.png`.
- [ ] Record a 30 to 60 second video of the homepage picks panels with the feed blocked on a lane VM. Save it as `artifacts/server-refactor/R11-review.mp4`.
- [ ] Post the screenshots and the video in chat with the `data/` diff from lane 10. Stop at merge-ready. Wait for the operator's click.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Lock the budgets and update the agent docs (R12)

**Depends on.** R11.

**Files.**

- [ ] Edit `tests/test_server_budget.py`.
- [ ] Edit `tests/test_import_layers.py`.
- [ ] Create `docs/architecture.md`.
- [ ] Edit `AGENTS.md`.
- [ ] Edit `tests/test_endpoint_contract.py` docstring.
- [ ] Delete `scripts/server_refactor_probes.py`.

**Build.**

- [ ] Set the final budgets. `server.py` has at most 150 lines, `from server import` appears only in `asgi_entry.py` and `scripts/restless_openapi.py`, and tests patch no `server` attribute.
- [ ] Add a budget case that fails when any file under `internal/` imports `server`.
- [ ] Finish `tests/test_import_layers.py`, which R2 created. The allowlist is now empty. It parses every module and fails when anything except `server.py` imports `internal.app`, when `internal.web` imports a feature package, or when a route module imports another route module. `internal/web/` holds what feature packages share, which is templating, settings, and reply helpers.
- [ ] Write `docs/architecture.md`. It holds the module tree from Appendix E, the import rules the two tests enforce, and where a new route, cache, or setting goes.
- [ ] Add `internal/app/`, `internal/web/`, `internal/home/`, and `internal/subnets/` to the ownership table in `AGENTS.md`.
- [ ] Update the sections of `AGENTS.md` that describe `server.py`. The conflict line for the two agents becomes the table in `internal/app/routers.py`.
- [ ] Add the one rule from #1186 that still applies. New logic goes in a module under `internal/`, and `tests/test_server_budget.py` enforces it.
- [ ] Delete the probe script. Its cases now live in the two bug test files.

**You see.**

- [ ] `pytest tests/test_server_budget.py` passes and fails again when you add `import server` to any file under `internal/`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_server_budget.py` gains the `internal/` import case. Run the full `pytest` suite and compare the failure list with the R0 list.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scripts/route_manifest.py --print` at trunk and at head. Save `/tmp/swarm-R12/worker-1/route-manifest.diff`. Pass when the set of method and path pairs is identical and the middleware order is identical.
- [ ] Lane 2. Load `/` in Chromium, once cold and once after 5 seconds. Save `/tmp/swarm-R12/worker-2/home-warm.png`. Pass when both loads contain `tribunal-hero` and the console shows zero errors.
- [ ] Lane 3. Request `/api/subnets?limit=5&sort=emission&order=desc`, `/api/summary`, and `/api/stats`. Save `/tmp/swarm-R12/worker-3/subnets.json`. Pass when each key set equals the trunk key set and `meta.total` is above 0.
- [ ] Lane 4. Send 20 concurrent `GET /api/daily-pick` requests. Save `/tmp/swarm-R12/worker-4/daily-pick-burst.json`. Pass when all 20 return 200 inside 1 second with the same `date`.
- [ ] Lane 5. Request `/api/top-picks`, `/api/top-pick/hour`, `/api/top-pick/day`, and `/api/daily-pick/weighed`. Save `/tmp/swarm-R12/worker-5/picks.json`. Pass when each key set equals the trunk key set.
- [ ] Lane 6. Request `/api/simivision` twice, 70 seconds apart. Save `/tmp/swarm-R12/worker-6/simivision.json`. Pass when the second response has the trunk key set and `data.meta.count` is above 0.
- [ ] Lane 7. Load `/pump` in Chromium and request `/api/pump-alerts`. Save `/tmp/swarm-R12/worker-7/pump.png`. Pass when the page renders the desk and the JSON has a `status` key.
- [ ] Lane 8. Send 50 concurrent `GET /` requests while polling `/health` every 100 ms. Save `/tmp/swarm-R12/worker-8/health-burst.txt`. Pass when every `/health` reply is `OK` in under 200 ms.
- [ ] Lane 9. Boot with `RUN_MODE=worker` and wait 60 seconds. Save `/tmp/swarm-R12/worker-9/worker-boot.log`. Pass when the log has `lifespan_ready` and no traceback.
- [ ] Lane 10. Run `python scripts/server_inventory.py . /tmp/inv.json` at trunk and head. Save `/tmp/swarm-R12/worker-10/inventory.txt`. Pass when head prints 150 lines or fewer, 0 routes in `server.py`, and 0 production importers besides `asgi_entry.py` and `scripts/restless_openapi.py`.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. p50 and p95 latency of warm `GET /`, `GET /api/subnets`, and `GET /api/daily-pick` over 200 requests each, plus the total of `python -X importtime -c "import server"`.
- [ ] Probe. Run `python scripts/perf_probe.py` five times at trunk and five times at head, alternating, on the same machine. The probe counts every reply that is not 200 and reports the median and range.
- [ ] Baseline. Record the trunk values first in `artifacts/server-refactor/R12/perf-trunk.json`.
- [ ] Rule. The PR fails when a head median is above the trunk median by more than 15 percent and by more than the trunk range, on any route or on import time. It also fails when the probe counts any reply that is not 200.

**Review gate.** None. R12 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Review comments triaged, each fixed or dismissed with a reason.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends the PR to the stack and the operator lands it.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] `wc -l server.py` prints 150 or fewer, and `python scripts/route_manifest.py --print` differs from the R0 manifest only in endpoint module names.
- [ ] Post one STATUS memory to Ditto and update board memory `f93f7202`, as `AGENTS.md` requires after a merge.
- [ ] Reply to the operator with the report that `playbooks/autopilot-stack.md` names.

## Appendix A. Prototype evidence

Every number below was measured on 2026-11-17 at commit `8cb247e` unless the line says otherwise. Rerun the two scripts to check them.

**Size.** `python scripts/server_inventory.py . /tmp/inv.json` prints 3,489 lines and 133,398 bytes, 107 functions, 31 route handlers, 1 class, 49 module globals, 27 top-level imports, 135 function-level imports from 68 modules, and 73 broad `except Exception` handlers. The app serves 198 routes, and `server.py` defines 31 of them. Ditto memory records the file at 179 KB on 2026-07-01 and 218 KB on 2026-07-05, before the FastAPI rebuild. The local clone is shallow, so git history cannot chart the growth since then.

**Coupling.** 158 of 489 test files import `server`. 20 test files patch a `server` attribute at 81 sites. 17 production modules import `server` back, always inside a function, for 9 helper names. `_get_subnets_with_source` alone is imported by 8 production modules and patched by 10 tests.

**The one fact that makes a move safe or unsafe.** A re-export does not keep test patches working. In a two-file prototype, `oldmod` re-exports `feed` and `route` from `newmod`, the test replaces `oldmod.feed`, and `route()` still returns the real value. So a move that leaves `from internal.x import name` in `server.py` keeps every import working and silently turns off every test that patches `server.name`. This is why each PR repoints its patch sites and why `tests/test_server_budget.py` counts them.

**Dead code.** `_resolve_index_context` has no caller in production. It is the only caller of `_build_index_context` and `_degraded_index_context`, which are the only callers of 7 more helpers. The functions total about 410 lines. `GET /` serves only the minimal and ultra-minimal shell today.

**Bugs confirmed by `scripts/server_refactor_probes.py`.** P1 to P10 map to the rows in Appendix F. The probe output on trunk was as follows.

```
P1 timestamp: 2026-11-17T05:02:34.529289+00:00Z
ROUTES total: 198 | defined in server.py module: 31
P2 /api/subnets on timeout -> (200, 'timeout', 'timeout', 'public, max-age=300')
P3 staking_data=None -> ('stats', 500, 'summary', 200)
P3b 6 requests -> 6 full rebuilds
P5 /api/simivision shapes -> {'cold_keys': ['meta', 'top'], 'warm_keys': ['data', 'status']}
P6 POST /api/mindmap/feedback bad body -> (200, '{"status":"error","detail":"JSON body required"}')
P7 /api/pick-explain on failure -> (200, {'status': 'error', 'netuid': 5, 'error': 'secret /app/data/path leaked'})
P8 static fallback -> {'source': 'static-fallback', 'rows': [('Coldint', 28.5), ('Inference', 15.2), ('Compute', 12.4)],
   'recorded': [('hold', 'Coldint', 28.5, False), ('prediction', 'Compute', 12.4, True), ('prediction', 'Inference', 15.2, True)]}
P9 index() is async: True | calls _ultra_minimal_index_html inline: True
P10 cache TTL defaults: _CACHE_PATHS['/']= 60 HOMEPAGE_SHELL_CACHE_SECONDS= 45.0
```

**The freeze never held.** `server.py` had 3,349 lines on 2026-09-03 when #1186 proposed the freeze, 3,421 on 2026-10-06, and 3,489 on 2026-11-15. The rule was never merged.

**A fix from #1330 that `main` still needs.** With the render patched to hang for 20 seconds, `_prime_emergency_home_html` returned after 20.3 seconds. Its timeout is 8 seconds.

**Route order does not constrain the moves.** A script matched a sample request for each of the 191 API routes against every other route. 3 ordered pairs overlap, none involves a route in `server.py`, and no method and path pair is defined twice.

**The template hides missing keys.** The Jinja environment uses the default `Undefined`, so a context key lost in R7 would print as an empty string and no test would fail.

**Import cost.** `import server` took 0.49, 0.49, and 0.52 seconds in 3 runs and loaded 1,103 modules at 93 MB. The 17 production modules that import it pay this cost on first use. The limiter was not profiled, so the perf rule compares medians against the run-to-run range.

**Settings and reply states are scattered.** `server.py` reads the environment 29 times for 22 names. It reads `HYDRATE_SUBNETS_TIMEOUT_SECONDS` in 5 places and `HOMEPAGE_SHELL_CACHE_SECONDS` with two defaults. It spells 12 different `status` strings by hand.

**Entrypoints.** Five commands import the app. They are `uvicorn server:app` in `.github/workflows/ci-smoke.yml`, `scripts/fly_worker_entrypoint.sh`, and `.replit`, then `asgi_entry:app` through `scripts/run_web_with_guard.py` and the `Procfile`, then `python server.py`, and `scripts/restless_openapi.py`.

**The local suite baseline is partial.** A full local run was stopped at 55 percent after about 25 minutes, with 2,794 passes and 83 failures. It also left 9 modified or new files under `data/` and `tests/`. PR #1591 reports 165 failures for the whole suite on `main`. R0 takes the full baseline from the CI artifact instead.

**Tests write tracked files.** `git status --short` was empty, then `pytest tests/test_endpoint_contract.py` passed 149 cases and left 6 modified files under `data/`.

**Settled by reading the code after the probes.** Neither recorder checks the source of a row, so D1 is real. The scheduler already records the audited hour pick at `internal/council/pick_scheduler.py:203`, so the write on the GET path is a duplicate.

**Answers from Ditto.** The Ditto main agent failed twice with `generation_failed`, so these come from stored memories.

- The shell-then-hydrate homepage is the intended design. A memory from 2026-08-26 records the empty server-rendered shell as expected behavior.
- Tools outside the dashboard read the API. Memories record automation reading `/api/subnets` and Ditto Code fetching the alert, daily-pick, and health routes. This supports keeping HTTP 200 for usable replies in R10.
- The operator set a standing review rule on 2026-11-16. The PR mechanics section applies it.
- PR #1578 changes 83 files and none of them is `server.py`, so the soul-map work does not collide with this plan.

**Unproven.** These stay open and each has a box in the plan that settles it.

- Whether production ever sends `staking_data` set to `None`. No code in the repo assigns `None` to it, so B6 is a latent fault, not a live one.
- What the `#1060 family` in PR #1186 meant. No memory or issue explains it.
- Whether a log filter outside the repo matches the logger name `server`. No memory records a log drain or an alert rule. Logs are pulled by hand with `flyctl`.
- D4 and D5 come from reading the code. No probe ran them.

**Independent review.** A Sonnet 5.5 subagent reviewed this plan against the code on 2026-11-17, as the standing review rule requires. It reported 3 blockers, 7 major findings, and 5 minor ones. Each was checked against the code and folded in. The blockers were the bailout wrapper that answers five paths before FastAPI, a production patch of `server` in `internal/council/build_seed_snapshot.py`, and helpers that R3 needed and no PR had assigned. The review confirmed the dead-code claims, the route counts, the free module names, and 10 of the bugs from the code. It did not run the probes, the tests, or the overlap script.

## Appendix B. Alternatives rejected

**A `server/` package with placeholder modules.** Tried on 2026-07-04. The agent built the layout and left every route as a placeholder. Ditto memory `d5edb12a` records it. `AGENTS.md` now forbids a parallel `server/` package.

**A script that splits the file mechanically.** Tried on 2026-07-05. The split lost globals and truncated functions, the Fly deploy failed, and the fix was a shim back to the monolith. Ditto memory `cd5fea37` records it. A script cannot see the 81 test patches or the 49 shared globals, which is where this file is coupled.

**A wrapper that imports the monolith and adds routes on top.** It hides the file and does not shrink it. Two foundations side by side caused the route-collision 422s that `AGENTS.md` describes.

**Re-exports in `server.py` for compatibility.** Rejected by the prototype in Appendix A. They keep imports green and switch test patches off.

**One large PR.** A break would be buried in a 3,000-line diff. Thirteen PRs each end in a state the route manifest can check.

**Moving routes first and helpers later.** Rejected because 17 production modules import helpers from `server`. A router module that needs those helpers would import `server` too, and the circular import would move into every new file. R2 and R3 remove that dependency before any route moves.

**Fixing bugs inside the move PRs.** Rejected, with one named exception in R5. A move PR that also changes behavior cannot be checked by comparing trunk and head output.

**Typed response models on every route.** A FastAPI `response_model` drops any key the model does not list. The payloads here are large dictionaries built by many modules, so adding models during the move would change bodies in PRs that must not change them. The golden files in R0 pin the bodies instead. Models can follow later, one route at a time.

**Holding all state on `app.state` with dependency injection.** It would touch every handler signature and every test. A registry with `reset_all()` gives tests the same isolation for a few lines.

**Splitting the other large files in the same program.** Seven files under `internal/` have more than 1,500 lines. They need the same treatment, and they are a separate plan that can reuse the R0 tools.

## Appendix C. Risks

**Decisions, all settled on 2026-11-17.** The operator asked for each open question to be answered by what is best for the repo.

- R1 deletes the full homepage build, because nothing calls it.
- R10 keeps HTTP 200 for a payload the page can still use and returns 503 only for a hard failure. `fetchJson` throws on any status other than 200 and drops the body, so a 503 on a `timeout` or `busy` payload would blank a panel that shows stale data today. A 503 on a hard failure costs the page nothing, since that body carries no data, and it lets the request metrics count failures.
- Close PR #1186. Its rule against campaigns contradicts this program, its diff adds three lines of fetch debris to the top of `AGENTS.md`, and its planned exception points at #1060, which closed on 2026-11-03 as an audit. R12 carries the one rule that still applies.
- Close PR #1330. It was parked on 2026-10-16 with three review blockers, and its patch no longer applies to `main`. The plan carries its fixes that `main` still lacks as R1, D8, and D9.
- D1 and D2 need no operator input. Reading `internal/learning/prediction_loop.py` and `internal/council/pick_scheduler.py` settled both.

**Open PRs that touch the same code.** The #1578 stack (#1599 to #1605, with #1606 on top of #1578) edits `internal/council/`, `internal/learning/`, and `server.py`. #1603 changes `_record_pick_in_learning_loop` in `server.py`, which R3 moves and R11 stops calling from a GET. It also grows `server.py` from 3,489 to 3,492 lines. Start R0 only after that stack lands, then take the R0 budget numbers from `main`. #1598 is already merged. #1591 now changes 6 files, including `internal/council/pump_overlay.py`, and is behind `main`. It is not test-only, and its landing is the owner's call. Rebase this branch onto `main` first, because it is 13 commits behind.

**Route order.** FastAPI matches routes in registration order. Appendix A shows that no route in `server.py` overlaps another, and the manifest checks the order of the 3 pairs that do.

**Two-agent ownership.** R2, R3, and R6 edit import lines inside packages that Agent A and Agent B own. The edits are one line each. Post them on the board first.

**Worker mode.** `_lifespan` has a worker branch that no contract test boots. Lane 9 and the R9 lane 10 cover it, and the owner of R9 watches the worker log after deploy.

**Cache behavior drift in R4.** The five caches differ in small ways that Appendix E lists. The characterization tests exist to catch a merged type that flattens a difference.

**Logger names.** Moved code logs under its new module name. Only the request log line keeps the name `server`. A log filter outside the repo that matches other `server` lines would miss them, and nothing in the repo can show whether one exists.

**No control skill.** The playbook expects `control-ui` or `control-cli`. Neither is installed here. Lanes use `curl` and Playwright as the boot recipe says.

**Model names.** The lane model is the playbook default. Run `/setup-pstack` to change it. The standing review rule pins the review subagent to Sonnet 5.5. `AGENTS.md` forbids Claude Sonnet 4.5 and 4.6 as subagents.

**Deploy.** No PR in this plan deploys. The operator runs the Fly workflow after landing, and the Deploy Guard runs the contract test again.

## Appendix D. Links and reading list

- Read `AGENTS.md`, `.cursor/rules/ponytail.mdc`, and `cursor-agents-communication/board.md` before editing.
- Run the **how** skill before R3, R4, and R7. They move code with shared state.
- Run the **architect** skill before R4 and the **interrogate** skill on the R4 and R7 diffs.
- Keep the decision trail per the **show-me-your-work** skill in `artifacts/server-refactor/decisions.tsv`, and commit it.
- Ditto memories used for history are `dc50b9e9`, `a7b7003b`, `cd5fea37`, and `d5edb12a`.

## Appendix E. Map of server.py

Line numbers are from commit `8cb247e`.

| Lines | What the block holds | Size | Target | PR |
|---|---|---|---|---|
| 1 to 197 | Imports, 16 guarded router imports, pick-engine and weights import guards | 197 | `internal/app/routers.py` | R9 |
| 199 to 436 | Boot helpers and `_lifespan` for web boot, worker boot, and heartbeat | 238 | `internal/app/lifespan.py` | R9 |
| 439 to 521 | App creation, load shed, worker proxy, metrics, rate limit, write auth, `include_router` calls | 83 | `server.py`, `internal/app/routers.py` | R9 |
| 523 to 567 | Jinja environment, filters, globals, static mount | 45 | `internal/web/templating.py` | R7 |
| 569 to 678 | `_CACHE_PATHS`, executor, `load_data`, row tagging, CORS and cache middleware | 110 | `internal/app/http_edge.py`, `internal/subnets/` | R2, R5, R9 |
| 681 to 740 | Timeouts, two executors, five caches with their locks, `_to_thread_timeout` | 60 | `internal/request_executor.py`, `internal/swr_cache.py` | R3, R4 |
| 743 to 1771 | Homepage shell, context builders, warm thread, `GET /` | 1029 | Delete about 410 lines, then `internal/home/` | R1, R7 |
| 1774 to 2354 | Registry, subnets, subnet, pool, summary, stats, soul-map, recommendations, daily-rotation | 581 | `internal/subnets/`, `internal/mindmap/` | R5, R8 |
| 2357 to 2418 | `POST /api/mindmap/feedback` | 62 | `internal/mindmap/` | R8 |
| 2421 to 2449 | Health, version, robots, favicon | 29 | `internal/health/routes.py` | R8 |
| 2452 to 2591 | Six preview pages, pump page, pump alerts | 140 | `internal/preview/routes.py`, `internal/pump/routes.py` | R8 |
| 2594 to 2706 | Static fallback rows, subnet source, market context | 113 | `internal/subnets/source.py`, `internal/council/market_context.py` | R2 |
| 2709 to 3023 | Learning-loop recording, hour picks, SimiVision board and cache | 315 | `internal/council/hour_picks.py`, `internal/simivision/board.py` | R3 |
| 3026 to 3442 | Routes for simivision, top-picks, daily-pick, weighed, pick-explain, top-pick day and hour | 417 | `internal/council/picks_routes.py` and the read modules | R3, R6 |
| 3445 to 3488 | Bailout wrapper, Restless wrapper, `__main__` | 44 | Stays in `server.py` | R9 |

The target tree adds three packages and reuses six that exist.

```
server.py                        app assembly only, 150 lines or fewer
internal/app/                    new. routers.py, lifespan.py, http_edge.py. Only server.py imports it
internal/web/                    new. templating.py, settings.py, replies.py. Shared by feature packages
internal/home/                   new. shell.py, context.py, routes.py
internal/swr_cache.py            new. one cache type
internal/request_executor.py     exists. gains the dashboard and pick-read pools
internal/subnets/                exists. gains source.py, registry.py, catalog.py, stats.py, routes.py
internal/council/                exists. gains market_context.py, hour_picks.py, daily_pick_read.py,
                                 top_picks_read.py, picks_routes.py
internal/simivision/             exists. gains board.py, and routes.py gains /api/simivision
internal/pump/, internal/preview/, internal/health/, internal/mindmap/
                                 exist. each gains the small routes that belong to it
```

The five caches that R4 merges differ as follows.

| Cache | Stale read | Cold read | Stores only if | Clock |
|---|---|---|---|---|
| Subnets | Serves stale and refreshes in a thread | Builds under a non-blocking lock, else registry fallback | Always | `time.time` |
| SimiVision | Serves stale and refreshes in a thread | Returns a busy shape and refreshes in a thread | Always | `time.time` |
| Top picks | Serves stale and refreshes in a thread | One caller builds, the rest read the disk snapshot | Payload has picks and no error | `time.time` |
| Hour pick | Rebuilds inline under a non-blocking lock | Same as stale | Always | `time.time` |
| Pump alerts | Rebuilds inline with no build lock | Same as stale | Status is not timeout or unavailable | `time.monotonic` |

## Appendix F. Bug register

Evidence is `measured` when a probe ran it and `read` when it comes from reading the code.

| Id | Bug | Evidence | Where today | PR |
|---|---|---|---|---|
| T1 | The contract test modifies 6 tracked files under `data/`. A stale signal store makes `GET /api/signals` regenerate inline | measured, cause read from #1330 and `internal/signals/routes.py:196` | test setup | R0 |
| B1 | A timeout payload from `/api/subnets` is sent with `Cache-Control` set to `public, max-age=300`, so a CDN can serve the failure for 5 minutes | measured, P2 | `server.py:659` | R10 |
| B2 | Error replies use HTTP 200 and include the exception text | measured, P6 and P7 | `server.py:2366`, `3154`, `3221`, `3340`, `3357`, `3442` | R10 |
| B3 | `/api/simivision` returns two different shapes, cold and warm | measured, P5 | `server.py:3023`, `3036` | R10 |
| B4 | Two defaults for `HOMEPAGE_SHELL_CACHE_SECONDS`, 60 and 45 | measured, P10 | `server.py:571`, `682` | R10 |
| B5 | A router that fails to import is dropped with one log line, and no endpoint reports it. `/api/health` is a constant | read | `server.py:32` to `171` | R10 |
| B6 | `/api/stats` returns 500 when a row has `staking_data` set to `None`, and `/api/summary` does not | measured for that input, P3. Latent, since no code assigns `None` | `server.py:2272` | R5 |
| D1 | When the feed fails, three invented subnets with invented prices reach the hold and shadow-prediction recorders | measured with stubbed recorders, P8, and the recorders have no source check | `server.py:2603`, `2630` | R11 |
| D2 | `GET /api/top-pick/hour` writes predictions to the learning loop | read | `server.py:2931`, `2954` | R11 |
| D3 | Timestamps end in `+00:00Z`, which is not valid ISO 8601 | measured, P1 | `server.py:2405`, `2802`, and 1 more production site | R11 |
| D4 | One row with a non-integer `netuid` stops the scan in `/api/subnet/{subnet_id}` and returns 404 for a real subnet | read | `server.py:2064` | R11 |
| D5 | `/api/mindmap/feedback` ignores feedback for netuid 0 | read | `server.py:2373` | R11 |
| D6 | `/api/summary` and `/api/stats` rebuild every subnet row on each request | measured, P3b | `server.py:2110`, `2257` | R11 |
| D7 | The `index` route handler is unreachable, because the bailout wrapper answers every `GET /`. Two homepage code paths exist and one never runs | read, found by the review | `server.py:1733`, `internal/instant_bailout.py:164` | R11 |
| D8 | The emergency homepage render waits for a hung worker past its 8 second timeout, because the `with` block joins the thread | measured, 20.3 seconds | `server.py:837` | R11 |
| D9 | The same `with` block bug sits on the live homepage path, in the learning-metrics load | read | `internal/learning/dashboard_context.py:120` | R11 |
| S1 | 73 broad `except Exception` handlers, many of which hide the failure behind a default | measured count | whole file | each move PR narrows the handlers it touches only when the caught state is illegitimate |

## Appendix G. Size of each PR

Lines are estimates from the ranges in Appendix E. Test patch sites are exact counts from `scripts/server_inventory.py` and they sum to 81.

| PR | Lines of `server.py` deleted or moved | Test patch sites to repoint or delete | Production importers to edit |
|---|---|---|---|
| R0 | 0 | 0 | 0 |
| R1 | about 435 deleted | 15 | 1 |
| R2 | about 135 | 23 | 14 |
| R3 | about 640 | 29 | 3 |
| R4 | about 150 removed by the shared cache type | 1, plus the direct references below | 0 |
| R5 | about 520 | 0 | 0 |
| R6 | about 250 | 0 | 0 |
| R7 | about 620 | 13 | 0 |
| R8 | about 270 | 0 | 0 |
| R9 | about 520 | 0 | 0 |
| R10 to R12 | Behavior fixes and tests, no moves | 0 | 0 |

The patch-site column undercounts the test work. Tests also read or write the moved globals directly at 107 places. About 58 touch homepage state and land in R1 and R7, and about 49 touch the pick and SimiVision caches and land in R3 and R4. The reset fixtures in R4 and R7 replace most of them.

R3 is the largest and riskiest PR. If its owner cannot keep the golden files unchanged in one pass, split it into the SimiVision board first and the pick modules second.

## Appendix H. Pass condition for each bug

Each row is what you can observe when the fix is in. Every fix PR commits the failing test for its row first.

| Id | Pass when |
|---|---|
| B1 | A timeout reply from `/api/subnets` carries `Cache-Control: no-store`. |
| B2 | A route that raises `RuntimeError("secret path")` returns a fixed error code and the reply body does not contain "secret". Usable replies stay HTTP 200 and a reply with no data is 503. A bad body on `POST /api/mindmap/feedback` returns 400. |
| B3 | `/api/simivision` cold, warm, and timed out all return the keys `status` and `data`. |
| B4 | One default exists for `HOMEPAGE_SHELL_CACHE_SECONDS`, and the public `max-age` on `/` equals the shell cache age. |
| B5 | Forcing an optional router import to fail makes its name appear under `routers` in the `/api/ops/live` report. |
| B6 | `GET /api/stats` returns 200 for a row whose `staking_data` is `None`. |
| D1 | With the subnet feed failing, no reply from the pick routes contains Coldint, Inference, or Compute, and they return their pending shape. D2 covers the data-file check. |
| D2 | `GET /api/top-pick/hour` leaves the learning ledger unchanged. |
| D3 | No timestamp the app emits contains `+00:00Z`, and the sweep key `isoformat_plus_Z_aware` reads 0. |
| D4 | A row with a non-integer `netuid` does not hide a real subnet from `GET /api/subnet/{id}`. |
| D5 | `POST /api/mindmap/feedback` with `subnet_id` 0 and a recommendation records the feedback once. |
| D6 | Six requests to `/api/stats` and `/api/summary` inside the cache window cause one row rebuild. |
| D7 | The `index` handler and the bailout wrapper return the same HTML for `/` in the cold, emergency, and warm states. |
| D8, D9 | A worker that hangs returns control within its timeout plus 1 second, and the sweep key `timeout_joined_by_with_block` reads 0. |
| S1 | The count of broad `except Exception` handlers in `tests/test_server_budget.py` is lower than before. |
