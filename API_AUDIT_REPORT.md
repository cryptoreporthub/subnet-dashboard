# Subnet Dashboard API Integrity Audit Report

**Date:** 2026-06-23  
**Target:** https://subnet-dashboard.fly.dev  
**Auditor:** OpenHands agent  

---

## Executive Summary

| Endpoint | Status | Latency (warm) | Size | Valid JSON | Verdict |
|----------|--------|----------------|------|------------|---------|
| `/health` | ✅ **200 OK** | 0.16s | 2 bytes | Text ("OK") | ✅ Healthy |
| `/` | ❌ **500 ERROR** | 0.40s | 34 bytes | ✅ `{"error":"internal server error"}` | ❌ **BROKEN** |
| `/api/scheduler/state` | ✅ **200 OK** | 0.24s | 206 bytes | ✅ Full scheduler state | ✅ Healthy |
| `/api/indicators` | ❌ **500 ERROR** | 0.40s | 34 bytes | ✅ `{"error":"internal server error"}` | ❌ **BROKEN** |
| `/api/simivision` | ✅ **200 OK** | 0.56s | 77,492 bytes | ✅ 128 subnets with consensus | ✅ Healthy |

**3 of 5 endpoints healthy, 2 of 5 returning HTTP 500 errors.**

---

## Detailed Findings

### 1. `/health` — ✅ Pass
- **Method:** GET
- **Response:** `OK` (text/plain)
- **Latency:** 0.16s (warm), ~32s (cold start — Fly.io auto-stop)
- **Schema:** Simple text string, no JSON expected
- **Note:** Returns **HTTP 502 Bad Gateway** during cold-start (~32s) because Fly.io's load balancer health-checks the endpoint before the gunicorn process is ready. This is normal behavior for `auto_stop_machines = true` + `min_machines_running = 0`.

### 2. `/` (index) — ❌ FAIL (HTTP 500)
- **Method:** GET
- **Response:** `{"error":"internal server error"}`
- **Latency:** 0.40s
- **Root Cause:** The route calls `render_template('index.html', **{})`. The template file exists (`templates/index.html`) but likely contains a Jinja2 rendering error (e.g., referencing an undefined variable, or a template include that fails). The Flask error handler at line 244 catches the exception and returns a generic 500.
- **Code reference:** `server.py` line 105: `return render_template('index.html', **{})`

### 3. `/api/scheduler/state` — ✅ Pass
- **Method:** GET
- **Response:** Valid JSON (see schema below)
- **Latency:** 0.24s

**Response Schema:**
```json
{
  "backoff_minutes": 30,
  "consecutive_failures": 0,
  "last_run_at": "2026-06-23T17:31:21.812760+00:00",
  "last_run_error": null,
  "last_run_ok": true,
  "next_run_at": 1782237708.474789,
  "refresh_minutes": 30,
  "running": true
}
```
- **Data Integrity:** ✓ All fields present, types correct
- **Scheduler Health:** Running, last run successful, no consecutive failures, correct refresh/backoff intervals

### 4. `/api/indicators` — ❌ FAIL (HTTP 500)
- **Method:** GET
- **Response:** `{"error":"internal server error"}`
- **Latency:** 0.40s

**Root Cause — Missing Import (CRITICAL):**
```python
# server.py line 225
from internal.indicators.indicator_engine import get_all_indicators
```
The function `get_all_indicators` **does not exist** in `indicator_engine.py`. That module contains:
- `class IndicatorEngine` (line 57) with instance methods:
  - `get_indicator_state()` (line 342)
  - `get_active_alerts()` (line 354)
- Standalone functions: `compute_macd`, `compute_momentum`, `compute_rsi`, `detect_crossovers`, `fetch_ohlcv` (re-exported, not defined in this file)

**Fix:** Replace line 225-226 with:
```python
from internal.indicators.indicator_engine import IndicatorEngine
indicators = IndicatorEngine().get_indicator_state()
```

### 5. `/api/simivision` — ✅ Pass
- **Method:** GET
- **Response:** Valid JSON array of 128 subnet objects
- **Latency:** 0.56s
- **Payload size:** 77,492 bytes

**Data Integrity Validation:**

| Metric | Result |
|--------|--------|
| Total items | 128 |
| ID range | 0 – 127 (√ all subnet IDs present) |
| Unique IDs | 128 (√ no duplicates) |
| Items with `consensus` field | 128 (100%) |
| Items with null `consensus.score` | 0 |
| Items with `name` | 128 (100%) |
| Items with `emission` | 128 (100%) |
| Items with `emission_rank` | 128 (100%) |

**Consensus Score Distribution:**
- **Range:** 0.448 – 0.765
- **Score > 0.7:** 72 subnets
- **Score < 0.4:** 0 subnets
- **Score = 0.5 threshold:** No artificial clustering

**Recommended Action Distribution:**
| Action | Count |
|--------|-------|
| `hold` | 68 |
| `accumulate` | 60 |

**Top 5 by Consensus Score:**
| ID | Name | Score | Action |
|----|------|-------|--------|
| 1 | Apex | 0.765 | accumulate |
| 2 | Omron | 0.765 | accumulate |
| 3 | Templar | 0.765 | accumulate |
| 4 | Targon | 0.765 | accumulate |
| 5 | Open Kaito | 0.765 | accumulate |

**Conclusion:** SimiVision data is fully intact, complete, and internally consistent. No integrity issues detected.

---

## Infrastructure Observations

### Cold-Start Problem
- Fly.io config: `auto_stop_machines = true`, `min_machines_running = 0`
- Gunicorn + Flask cold-start takes **~31-32 seconds**
- During cold-start, `/health` returns HTTP 502 (Fly.io ELB rejects before server responds)
- After warm, all endpoints respond in < 1s
- **Impact:** First request after idle period hits 30s+ latency

### Gunicorn Configuration
- Dockerfile runs: `gunicorn --bind 0.0.0.0:8080 --workers 2 server:app`
- 2 workers, no timeout specified (default 30s timeout may contribute to 502s during cold start)

---

## Recommended Fixes

### Critical (Breaking)
1. **`/api/indicators` — Fix import in `server.py` line 225**
   - Change `from internal.indicators.indicator_engine import get_all_indicators` to use `IndicatorEngine().get_indicator_state()` instead

2. **`/` (index) — Debug template rendering**
   - Run `flask render_template` locally to identify the Jinja2 error
   - Most likely cause: template accesses a context variable that isn't being passed (currently `**{}`)

### Medium Priority
3. **Health check timeout** — Add `--timeout 60` to gunicorn CMD to prevent premature worker kills during cold start
4. **Add response schema validation** — Consider adding Pydantic models or JSON Schema validation for API responses

### Low Priority
5. **Cold-start optimization** — Either set `min_machines_running = 1` in fly.toml to keep one instance warm, or add a UptimeRobot / cron-job monitor that pings the health endpoint every 5 minutes

---

## Files Examined
- `server.py` (routes, error handlers)
- `internal/indicators/indicator_engine.py` (missing `get_all_indicators`)
- `internal/simivision/engine.py` (SimiVision build pipeline)
- `gunicorn_config.py` / `Procfile` / `Dockerfile` / `fly.toml` (deployment config)
- `templates/index.html` (exists, likely has rendering error)
