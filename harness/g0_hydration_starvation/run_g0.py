#!/usr/bin/env python3
"""G0 headless-browser harness for #1058 homepage hydration starvation.

Measure-only. Two independent prod runs must agree before any P1 product diff.

Usage:
  source .venv/bin/activate
  python harness/g0_hydration_starvation/run_g0.py \\
      --base-url https://subnet-dashboard.fly.dev \\
      --run-id prod-1 \\
      --out-dir artifacts/g0-baseline/prod-1

Do not add playwright to requirements.txt; install into the venv:
  pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

HERO_CRITICAL_PATHS = (
    "/api/learning/stats",
    "/api/daily-pick",
)
HERO_SUPPORTING_PATHS = (
    "/api/subnets",
    "/api/learning-metrics",
)
PLACEHOLDER_TITLE = "Awaiting subnet"
WAIT_S = 50.0
HEALTH_INTERVAL_S = 0.25
HERO_BUDGET_S = 10.0
PENDING_CUTOFF_S = 45.0
MACHINE_WARM_MS = 500.0
MACHINE_COLD_MS = 1000.0


def probe_machine_state(base_url: str, *, probes: int = 3) -> Dict[str, Any]:
    """Pre-navigation /health probes — warm vs cold/contended host."""
    health_url = base_url.rstrip("/") + "/health"
    samples: List[Dict[str, Any]] = []
    for _ in range(probes):
        t0 = time.perf_counter()
        status = None
        ok = False
        err = None
        try:
            req = urllib.request.Request(
                health_url,
                headers={"Accept": "text/plain", "Cache-Control": "no-cache"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                status = resp.status
                body = resp.read(32).decode("utf-8", errors="replace")
                ok = status == 200 and body.strip() == "OK"
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        samples.append(
            {
                "latency_ms": elapsed_ms,
                "status": status,
                "ok": ok,
                "error": err,
            }
        )

    latencies = [s["latency_ms"] for s in samples]
    errors = [s for s in samples if not s["ok"]]
    timed_out = any(
        s["error"] and "timeout" in str(s["error"]).lower() for s in samples
    )
    slow = any(ms >= MACHINE_COLD_MS for ms in latencies)
    warm = bool(latencies) and all(ms < MACHINE_WARM_MS for ms in latencies) and not errors

    if timed_out or slow:
        state = "contended" if len(errors) >= 2 or timed_out else "cold"
    elif warm:
        state = "warm"
    elif errors:
        state = "cold"
    else:
        state = "contended"

    return {
        "machine_state": state,
        "probes": samples,
        "p50_ms": round(percentile(latencies, 50) or 0.0, 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
    }


def _first_hero_api_timing(requests: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for path_prefix, key in (
        ("/api/learning/stats", "learning_stats"),
        ("/api/daily-pick", "daily_pick"),
    ):
        matches = [
            r
            for r in requests.values()
            if r.get("path", "").startswith(path_prefix)
        ]
        if not matches:
            continue
        first = min(matches, key=lambda x: x["start_s"])
        out[key] = {
            "path": first["path"],
            "start_s": first["start_s"],
            "end_s": first["end_s"],
            "duration_ms": first["duration_ms"],
            "status": first["status"],
        }
    return out


def _collect_critical_path_timing(page) -> Dict[str, Any]:
    return page.evaluate(
        """() => {
          const nav = performance.getEntriesByType('navigation')[0];
          const resources = performance.getEntriesByType('resource');
          const scripts = resources.filter((r) => {
            const name = String(r.name || '');
            return r.initiatorType === 'script' || /\\/static\\/js\\/.*\\.js(\\?|$)/.test(name);
          });
          let firstScript = null;
          for (const s of scripts) {
            if (!firstScript || s.startTime < firstScript.startTime) {
              firstScript = {
                name: s.name,
                startTime: s.startTime,
                responseEnd: s.responseEnd,
                duration: s.duration,
              };
            }
          }
          const dcl = nav ? nav.domContentLoadedEventEnd : null;
          let scriptWallBeforeDcl = null;
          if (dcl != null) {
            for (const s of scripts) {
              const end = s.responseEnd || (s.startTime + s.duration);
              if (end <= dcl && (!scriptWallBeforeDcl || end > scriptWallBeforeDcl.responseEnd)) {
                scriptWallBeforeDcl = {
                  name: s.name,
                  startTime: s.startTime,
                  responseEnd: end,
                  duration: s.duration,
                };
              }
            }
          }
          const marks = {};
          for (const name of ['html-parse', 'hydrate-start', 'hydrate-end']) {
            const entries = performance.getEntriesByName(name, 'mark');
            if (entries.length) {
              marks[name] = round(entries[0].startTime, 3);
            }
          }
          const measures = {};
          for (const name of ['hydrate']) {
            const entries = performance.getEntriesByName(name, 'measure');
            if (entries.length) {
              measures[name] = {
                startTime: round(entries[0].startTime, 3),
                duration: round(entries[0].duration, 3),
              };
            }
          }
          function round(n, d) {
            d = d == null ? 3 : d;
            return Math.round(Number(n) * Math.pow(10, d)) / Math.pow(10, d);
          }
          return {
            marks,
            measures,
            first_script: firstScript,
            script_wall_before_dcl: scriptWallBeforeDcl,
            dom_interactive: nav ? round(nav.domInteractive, 3) : null,
            dom_content_loaded: nav ? round(nav.domContentLoadedEventEnd, 3) : null,
            load_event_end: nav ? round(nav.loadEventEnd, 3) : null,
            html_ttfb: nav ? round(nav.responseStart, 3) : null,
          };
        }"""
    )


def _median(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(statistics.median(nums), 3)


def critpath_median_table(crit_id: str, summaries: List[Dict[str, Any]]) -> str:
    dcl = [s.get("navigation_timing", {}).get("domContentLoadedEventEnd") for s in summaries]
    stats = [
        (s.get("hero_api_timing") or {}).get("learning_stats", {}).get("start_s")
        for s in summaries
    ]
    hero = [s.get("hero_complete_at_s") for s in summaries]
    states = [s.get("machine_state") for s in summaries]
    return f"""# Critical path median — `{crit_id}`

Runs: {len(summaries)}

| Metric | Median |
|--------|--------|
| DCL (domContentLoadedEventEnd ms) | {_median(dcl)} |
| /api/learning/stats start (probe s) | {_median(stats)} |
| Hero complete (probe s) | {_median(hero)} |
| machine_state (mode) | {max(set(states), key=states.count) if states else 'n/a'} |

Per-run dirs: `artifacts/g0-baseline/critpath-{crit_id}-{{1,2,3}}/`
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or "/"


def _is_api(url: str) -> bool:
    return "/api/" in _path_of(url)


def _classify_api(path: str) -> str:
    if path.startswith("/api/daily-pick"):
        return "hero-critical" if path == "/api/daily-pick" or path.startswith("/api/daily-pick?") else "hero-supporting"
    if path.startswith("/api/learning/stats"):
        return "hero-critical"
    if any(path.startswith(p) for p in HERO_SUPPORTING_PATHS):
        return "hero-supporting"
    return "secondary"


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


class HealthPoller:
    def __init__(self, health_url: str, interval_s: float = HEALTH_INTERVAL_S):
        self.health_url = health_url
        self.interval_s = interval_s
        self.samples: List[Dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="g0-health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            wall = time.time()
            status = None
            err = None
            body = ""
            try:
                req = urllib.request.Request(
                    self.health_url,
                    headers={"Accept": "text/plain", "Cache-Control": "no-cache"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    status = resp.status
                    body = resp.read(32).decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 — capture every probe outcome
                err = f"{type(exc).__name__}: {exc}"
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.samples.append(
                {
                    "t_unix": wall,
                    "latency_ms": round(elapsed_ms, 2),
                    "status": status,
                    "ok": status == 200 and body.strip() == "OK",
                    "error": err,
                }
            )
            remaining = self.interval_s - (time.perf_counter() - t0)
            if remaining > 0:
                self._stop.wait(remaining)

    def summary(self, t0_unix: float, t1_unix: float) -> Dict[str, Any]:
        window = [s for s in self.samples if t0_unix <= s["t_unix"] <= t1_unix]
        latencies = [s["latency_ms"] for s in window]
        return {
            "n": len(window),
            "ok": sum(1 for s in window if s["ok"]),
            "errors": sum(1 for s in window if not s["ok"]),
            "p50_ms": round(percentile(latencies, 50) or 0.0, 2) if latencies else None,
            "p95_ms": round(percentile(latencies, 95) or 0.0, 2) if latencies else None,
            "p100_ms": round(max(latencies), 2) if latencies else None,
            "min_ms": round(min(latencies), 2) if latencies else None,
            "mean_ms": round(statistics.mean(latencies), 2) if latencies else None,
        }


def _hero_snapshot(page) -> Dict[str, Any]:
    return page.evaluate(
        """() => {
          const hero = document.getElementById('tribunal-hero');
          const titleEl = document.getElementById('tribunal-hero-title');
          const title = titleEl ? String(titleEl.textContent || '').trim() : null;
          const verdict = hero ? hero.getAttribute('data-verdict-kind') : null;
          const stage = document.getElementById('section-daily-pick');
          const warming = !!(stage && stage.getAttribute('data-shell-warming') === '1');
          const hydrate = document.documentElement.dataset.hydrate || null;
          const gradedEl = hero && hero.querySelector('[data-accuracy-graded]');
          const subEl = hero && hero.querySelector('[data-accuracy-sub]');
          const graded = gradedEl ? String(gradedEl.textContent || '').trim() : null;
          const accSub = subEl ? String(subEl.textContent || '').trim() : null;
          const badge = document.getElementById('k3-action-badge');
          const badgeText = badge ? String(badge.textContent || '').trim() : null;
          const placeholderTitle = title === 'Awaiting subnet';
          const cold = verdict === 'cold';
          const statsParsed = !!(window.SimiLearning && window.SimiLearning.stats);
          const statsGraded = statsParsed
            ? Number((window.SimiLearning.stats.trust_banner || {}).graded ||
                     window.SimiLearning.stats.graded || 0)
            : null;
          return {
            title, verdict, warming, hydrate, graded, accSub, badgeText,
            placeholderTitle, cold, statsParsed, statsGraded,
            needsHydrate: !!(cold || placeholderTitle),
            heroPresent: !!hero,
          };
        }"""
    )


def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    har_path = out_dir / "session.har"
    screenshot_early = out_dir / "hero_t10s.png"
    screenshot_late = out_dir / "hero_t45s.png"
    console_path = out_dir / "console.jsonl"

    base = args.base_url.rstrip("/")
    health_url = base + "/health"
    page_url = base + "/"

    machine_probe = probe_machine_state(base)
    requests: Dict[int, Dict[str, Any]] = {}
    events: List[Dict[str, Any]] = []
    console_lines: List[Dict[str, Any]] = []
    inflight = 0
    max_inflight = 0
    inflight_api = 0
    max_inflight_api = 0
    seq = 0
    t_origin = time.perf_counter()
    t_origin_unix = time.time()
    hero_complete_at: Optional[float] = None
    stats_parsed_at: Optional[float] = None
    hero_dom_ready_at: Optional[float] = None
    hero_snapshots: List[Dict[str, Any]] = []

    def elapsed() -> float:
        return time.perf_counter() - t_origin

    def on_request(req) -> None:
        nonlocal seq, inflight, max_inflight, inflight_api, max_inflight_api
        seq += 1
        rid = seq
        req._g0_id = rid  # type: ignore[attr-defined]
        path = _path_of(req.url)
        rec = {
            "id": rid,
            "url": req.url,
            "path": path,
            "method": req.method,
            "resource_type": req.resource_type,
            "is_api": _is_api(req.url),
            "class": _classify_api(path) if _is_api(req.url) else req.resource_type,
            "start_s": round(elapsed(), 3),
            "end_s": None,
            "duration_ms": None,
            "status": None,
            "failure": None,
            "aborted": False,
        }
        requests[rid] = rec
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        if rec["is_api"]:
            inflight_api += 1
            max_inflight_api = max(max_inflight_api, inflight_api)
        events.append({"t_s": rec["start_s"], "kind": "request", "id": rid, "path": path})

    def finish_request(req, *, status=None, failure=None, aborted=False) -> None:
        nonlocal inflight, inflight_api
        rid = getattr(req, "_g0_id", None)
        rec = requests.get(rid) if rid is not None else None
        if rec is None:
            return
        if rec["end_s"] is not None:
            return
        rec["end_s"] = round(elapsed(), 3)
        rec["duration_ms"] = round((rec["end_s"] - rec["start_s"]) * 1000.0, 1)
        rec["status"] = status
        rec["failure"] = failure
        rec["aborted"] = aborted or (failure or "").upper().find("ABORT") >= 0
        inflight = max(0, inflight - 1)
        if rec["is_api"]:
            inflight_api = max(0, inflight_api - 1)
        events.append(
            {
                "t_s": rec["end_s"],
                "kind": "abort" if rec["aborted"] else "finish",
                "id": rec["id"],
                "path": rec["path"],
                "status": status,
                "failure": failure,
            }
        )

    health = HealthPoller(health_url)
    health.start()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 G0Harness/1058"
            ),
            record_har_path=str(har_path),
            record_har_content="embed",
        )
        context.set_default_timeout(60000)
        page = context.new_page()
        try:
            cdp = context.new_cdp_session(page)
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        except Exception:
            pass
        page.on("request", on_request)

        def _on_finished(req) -> None:
            status = None
            try:
                resp = req.response()
                status = resp.status if resp is not None else None
            except Exception:
                status = None
            finish_request(req, status=status)

        page.on("requestfinished", _on_finished)
        page.on(
            "requestfailed",
            lambda req: finish_request(
                req,
                failure=req.failure or "failed",
                aborted=True,
            ),
        )
        page.on(
            "console",
            lambda msg: console_lines.append(
                {
                    "t_s": round(elapsed(), 3),
                    "type": msg.type,
                    "text": msg.text,
                    "location": str(msg.location),
                }
            ),
        )
        page.on(
            "pageerror",
            lambda err: console_lines.append(
                {"t_s": round(elapsed(), 3), "type": "pageerror", "text": str(err)}
            ),
        )

        nav_started = elapsed()
        nav_response = page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        nav_dcl = elapsed()
        document_server_timing = None
        if nav_response is not None:
            document_server_timing = nav_response.headers.get("server-timing")

        deadline = t_origin + WAIT_S
        t10_shot = False
        t45_shot = False
        while time.perf_counter() < deadline:
            try:
                snap = _hero_snapshot(page)
            except Exception as exc:  # noqa: BLE001 — keep probe alive across reloads
                events.append({"t_s": round(elapsed(), 3), "kind": "snapshot_error", "error": str(exc)})
                page.wait_for_timeout(250)
                continue
            now_s = elapsed()
            snap["t_s"] = round(now_s, 3)
            hero_snapshots.append(snap)
            if snap.get("statsParsed") and stats_parsed_at is None:
                stats_parsed_at = now_s
                events.append({"t_s": round(now_s, 3), "kind": "STATS_PARSED"})
            if (not snap.get("needsHydrate")) and snap.get("heroPresent") and hero_dom_ready_at is None:
                hero_dom_ready_at = now_s
                events.append({"t_s": round(now_s, 3), "kind": "HERO_DOM_READY", "title": snap.get("title")})
            if (
                hero_complete_at is None
                and stats_parsed_at is not None
                and hero_dom_ready_at is not None
            ):
                hero_complete_at = max(stats_parsed_at, hero_dom_ready_at)
                events.append(
                    {
                        "t_s": round(hero_complete_at, 3),
                        "kind": "HERO_COMPLETE_AT",
                        "stats_parsed_at": round(stats_parsed_at, 3),
                        "hero_dom_ready_at": round(hero_dom_ready_at, 3),
                        "title": snap.get("title"),
                        "verdict": snap.get("verdict"),
                        "statsGraded": snap.get("statsGraded"),
                    }
                )
            if not t10_shot and now_s >= 10.0:
                page.screenshot(path=str(screenshot_early), full_page=False)
                t10_shot = True
            if not t45_shot and now_s >= PENDING_CUTOFF_S:
                page.screenshot(path=str(screenshot_late), full_page=False)
                t45_shot = True
            page.wait_for_timeout(250)

        if not t10_shot:
            page.screenshot(path=str(screenshot_early), full_page=False)
        if not t45_shot:
            page.screenshot(path=str(screenshot_late), full_page=False)

        nav_timing = page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0];
              if (!nav) return null;
              return {
                type: nav.type,
                startTime: nav.startTime,
                unloadEventEnd: nav.unloadEventEnd,
                domInteractive: nav.domInteractive,
                domContentLoadedEventEnd: nav.domContentLoadedEventEnd,
                loadEventEnd: nav.loadEventEnd,
                responseStart: nav.responseStart,
                responseEnd: nav.responseEnd,
                duration: nav.duration,
                transferSize: nav.transferSize,
                encodedBodySize: nav.encodedBodySize,
              };
            }"""
        )
        critical_path = _collect_critical_path_timing(page)
        hero_api_timing = _first_hero_api_timing(requests)
        final_hero = _hero_snapshot(page)
        final_hero["t_s"] = round(elapsed(), 3)

        pending_at_45 = [
            rec
            for rec in requests.values()
            if rec["is_api"]
            and rec["start_s"] <= PENDING_CUTOFF_S
            and (rec["end_s"] is None or rec["end_s"] > PENDING_CUTOFF_S)
        ]
        still_open = [rec for rec in requests.values() if rec["end_s"] is None]

        context.close()
        browser.close()

    health.stop()
    t_end_unix = time.time()
    health_summary = health.summary(t_origin_unix, t_end_unix)

    api_recs = [r for r in requests.values() if r["is_api"]]
    aborted = [r for r in api_recs if r["aborted"] or (r["failure"] and "abort" in str(r["failure"]).lower())]
    hung = [r for r in api_recs if r["end_s"] is None or (r["duration_ms"] or 0) > PENDING_CUTOFF_S * 1000]
    aborted_or_hung = {r["id"]: r for r in aborted + hung}

    hero_critical_failed = [
        r
        for r in aborted_or_hung.values()
        if r["class"] == "hero-critical"
        or any(r["path"].startswith(p) for p in HERO_CRITICAL_PATHS)
    ]

    homepage_ttfb_ms = None
    homepage_status = None
    homepage_err = None
    try:
        ttfb_t0 = time.perf_counter()
        req = urllib.request.Request(page_url, method="GET", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            homepage_status = resp.status
            resp.read(64)
        homepage_ttfb_ms = round((time.perf_counter() - ttfb_t0) * 1000.0, 1)
    except Exception as exc:  # noqa: BLE001
        homepage_err = f"{type(exc).__name__}: {exc}"
        homepage_ttfb_ms = round((time.perf_counter() - ttfb_t0) * 1000.0, 1)

    starvation = bool(
        hero_complete_at is None or hero_complete_at > HERO_BUDGET_S
    ) and bool(hero_critical_failed or pending_at_45 or hung)

    hydrates_in_budget = hero_complete_at is not None and hero_complete_at <= HERO_BUDGET_S

    summary = {
        "run_id": args.run_id,
        "base_url": base,
        "captured_at": _utc_now(),
        "wait_s": WAIT_S,
        "hero_budget_s": HERO_BUDGET_S,
        "hero_complete_at_s": round(hero_complete_at, 3) if hero_complete_at is not None else None,
        "stats_parsed_at_s": round(stats_parsed_at, 3) if stats_parsed_at is not None else None,
        "hero_dom_ready_at_s": round(hero_dom_ready_at, 3) if hero_dom_ready_at is not None else None,
        "hydrates_in_budget": hydrates_in_budget,
        "starvation_shape": starvation,
        "nav_domcontentloaded_s": round(nav_dcl - nav_started, 3),
        "machine_state": machine_probe.get("machine_state"),
        "machine_probe": machine_probe,
        "document_server_timing": document_server_timing,
        "critical_path": critical_path,
        "hero_api_timing": hero_api_timing,
        "navigation_timing": nav_timing,
        "final_hero": final_hero,
        "aborted_endpoints": [
            {
                "path": r["path"],
                "class": r["class"],
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "duration_ms": r["duration_ms"],
                "status": r["status"],
                "failure": r["failure"],
                "hero_critical": r["class"] == "hero-critical",
            }
            for r in sorted(aborted_or_hung.values(), key=lambda x: x["start_s"])
        ],
        "aborted_hero_critical": [
            r["path"] for r in hero_critical_failed
        ],
        "health": health_summary,
        "health_p95_over_budget": bool(
            health_summary.get("p95_ms") is not None and health_summary["p95_ms"] >= 500
        ),
        "max_concurrent_inflight": max_inflight,
        "max_concurrent_inflight_api": max_inflight_api,
        "pending_api_at_45s": [
            {"path": r["path"], "class": r["class"], "start_s": r["start_s"], "end_s": r["end_s"]}
            for r in pending_at_45
        ],
        "still_open_at_close": [{"path": r["path"], "start_s": r["start_s"]} for r in still_open],
        "api_request_count": len(api_recs),
        "homepage_curl_sanity": {
            "status": homepage_status,
            "ttfb_ms": homepage_ttfb_ms,
            "error": homepage_err,
            "note": "sanity-only, not a G0 pass/fail gate",
        },
        "artifacts": {
            "har": str(har_path),
            "screenshot_t10s": str(screenshot_early),
            "screenshot_t45s": str(screenshot_late),
        },
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "requests.json").write_text(json.dumps(list(requests.values()), indent=2) + "\n")
    (out_dir / "events.json").write_text(json.dumps(events, indent=2) + "\n")
    (out_dir / "hero_snapshots.json").write_text(json.dumps(hero_snapshots, indent=2) + "\n")
    (out_dir / "health_series.json").write_text(json.dumps(health.samples, indent=2) + "\n")
    console_path.write_text("".join(json.dumps(line) + "\n" for line in console_lines))

    md = _markdown_table(summary)
    (out_dir / "baseline.md").write_text(md)
    print(md)
    return summary


def _markdown_table(s: Dict[str, Any]) -> str:
    aborted = s.get("aborted_endpoints") or []
    aborted_paths = ", ".join(sorted({a["path"] for a in aborted})) or "(none)"
    hero_crit = ", ".join(s.get("aborted_hero_critical") or []) or "(none)"
    pending = s.get("pending_api_at_45s") or []
    pending_paths = ", ".join(sorted({p["path"] for p in pending})) or "(none)"
    h = s.get("health") or {}
    hero_at = s.get("hero_complete_at_s")
    hero_cell = "NEVER" if hero_at is None else f"{hero_at:.3f}s"
    shape = "STARVATION" if s.get("starvation_shape") else (
        "HYDRATES_IN_BUDGET" if s.get("hydrates_in_budget") else "SLOW_BUT_COMPLETE"
    )
    return f"""# G0 baseline — `{s.get("run_id")}`

Captured: {s.get("captured_at")}
Base: {s.get("base_url")}
Shape: **{shape}**

| Metric | Value |
|--------|-------|
| Hero complete time | {hero_cell} (budget ≤ {s.get("hero_budget_s")}s) |
| stats parsed at | {s.get("stats_parsed_at_s")} |
| hero DOM ready at | {s.get("hero_dom_ready_at_s")} |
| Final title | `{((s.get("final_hero") or {}).get("title"))}` |
| Final verdict | `{((s.get("final_hero") or {}).get("verdict"))}` |
| Final graded | `{((s.get("final_hero") or {}).get("graded"))}` / statsGraded={((s.get("final_hero") or {}).get("statsGraded"))} |
| Aborted/hung endpoints | {aborted_paths} |
| Aborted hero-critical | {hero_crit} |
| /health n / ok | {h.get("n")} / {h.get("ok")} |
| /health p50 / p95 / p100 | {h.get("p50_ms")} / {h.get("p95_ms")} / {h.get("p100_ms")} ms |
| /health p95 over 500ms | {s.get("health_p95_over_budget")} |
| Max concurrent in-flight (all / api) | {s.get("max_concurrent_inflight")} / {s.get("max_concurrent_inflight_api")} |
| Pending API still outstanding at t=45s | {pending_paths} |
| API request count | {s.get("api_request_count")} |
| Homepage curl TTFB (sanity) | {((s.get("homepage_curl_sanity") or {}).get("ttfb_ms"))} ms status={((s.get("homepage_curl_sanity") or {}).get("status"))} |
| machine_state | {s.get("machine_state")} |
| document Server-Timing | {s.get("document_server_timing")} |
| html-parse mark (ms) | {((s.get("critical_path") or {}).get("marks") or {}).get("html-parse")} |
| hydrate-start / hydrate-end (ms) | {((s.get("critical_path") or {}).get("marks") or {}).get("hydrate-start")} / {((s.get("critical_path") or {}).get("marks") or {}).get("hydrate-end")} |
| stats / daily-pick start (probe s) | {((s.get("hero_api_timing") or {}).get("learning_stats") or {}).get("start_s")} / {((s.get("hero_api_timing") or {}).get("daily_pick") or {}).get("start_s")} |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `{s.get("starvation_shape")}`
"""


def run_critpath_batch(args: argparse.Namespace) -> int:
    crit_id = args.critpath_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_out = Path(args.critpath_out or "artifacts/g0-baseline")
    summaries: List[Dict[str, Any]] = []
    for i in range(1, args.critpath_n + 1):
        run_args = argparse.Namespace(
            base_url=args.base_url,
            run_id=f"critpath-{crit_id}-{i}",
            out_dir=str(base_out / f"critpath-{crit_id}-{i}"),
        )
        print(f"\n=== critpath run {i}/{args.critpath_n} → {run_args.out_dir} ===\n")
        summaries.append(run_probe(run_args))
    median_md = critpath_median_table(crit_id, summaries)
    median_path = base_out / f"critpath-{crit_id}-median.md"
    median_path.parent.mkdir(parents=True, exist_ok=True)
    median_path.write_text(median_md)
    median_json = base_out / f"critpath-{crit_id}-median.json"
    median_json.write_text(
        json.dumps(
            {
                "crit_id": crit_id,
                "runs": [s.get("run_id") for s in summaries],
                "machine_state": [s.get("machine_state") for s in summaries],
                "median": {
                    "dcl_ms": _median(
                        [
                            s.get("navigation_timing", {}).get("domContentLoadedEventEnd")
                            for s in summaries
                        ]
                    ),
                    "stats_start_s": _median(
                        [
                            (s.get("hero_api_timing") or {})
                            .get("learning_stats", {})
                            .get("start_s")
                            for s in summaries
                        ]
                    ),
                    "hero_complete_s": _median([s.get("hero_complete_at_s") for s in summaries]),
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(median_md)
    print(f"\nWrote {median_path} and {median_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="G0 hydration starvation harness (#1058)")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument(
        "--critpath",
        action="store_true",
        help="Run n sequential cold loads and write critpath median table",
    )
    parser.add_argument("--critpath-id", default=None, help="ID for critpath-{id}-{1,2,3}/ dirs")
    parser.add_argument("--critpath-n", type=int, default=3, help="Sequential runs for --critpath")
    parser.add_argument(
        "--critpath-out",
        default="artifacts/g0-baseline",
        help="Base output dir for --critpath runs",
    )
    args = parser.parse_args()
    if args.critpath:
        return run_critpath_batch(args)
    if not args.run_id or not args.out_dir:
        parser.error("--run-id and --out-dir are required unless --critpath is set")
    run_probe(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
