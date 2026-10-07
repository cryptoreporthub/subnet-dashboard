# F02 static re-run receipt — termination-path sweep

| Field | Value |
|---|---|
| Status | **COMPLETE** |
| Pin | `ce3d820013d45577333ac8aada8c0d9e97c54129` |
| Executed | 2026-10-06T20:05Z |
| Executor | MC worker `bc-c00c677f-a9f1-5cf3-9bc3-f36c5f5199fe` |
| Audit anchor | [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) |
| Supersedes | Registry v1.7 F02 raw receipt @ pin `e58bd17f…` (same sweep, older pin) |

**Scope:** source-static termination-path sweep only (Gate A). Runtime env and orchestrator boundaries remain separate (see Gate C prod env receipt).

---

## Command

```bash
PIN=ce3d820013d45577333ac8aada8c0d9e97c54129
git grep -n -E 'os\._exit|sys\.exit|signal\.signal' "$PIN" -- internal/ scripts/
echo "EXIT=$?"
```

## Raw result

```text
EXIT=0
MATCH_COUNT=58
```

Product-runtime matches (tests/harness excluded by inspection):

```text
ce3d8200:internal/loop_stall_guard.py:217:                os._exit(1)
ce3d8200:internal/worker.py:89:    signal.signal(signal.SIGTERM, _handle_signal)
ce3d8200:internal/worker.py:90:    signal.signal(signal.SIGINT, _handle_signal)
ce3d8200:internal/worker.py:156:        sys.exit(0)
ce3d8200:scripts/fly_web_entrypoint.sh:53:      elif ! python -c "from internal.worker_heartbeat import is_alive; import sys; sys.exit(0 if is_alive(max_age_seconds=180) else 1)"; then
```

Additional `scripts/fly_web_entrypoint.sh` `kill` / stale-worker restart lines at `:28`, `:51-55` (per registry v1.7 baseline) — unchanged at this pin.

CI/script one-shot `sys.exit` matches (54 lines) are out of product runtime scope per F02 scope doc §1.

---

## Verdict

**PASS (source-static scope).** Multiple independent termination paths remain; `os._exit(1)` in `loop_stall_guard.py:217` is **not** the sole path. Matches registry v1.7 F02 raw receipt structure at the updated audit pin.

**NOT CLAIMED:** effective runtime values, Fly/orchestrator kill behavior, dynamic-library termination, deployed image SHA.
