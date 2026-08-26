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

    health = HealthPoller(health_url)
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
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        nav_dcl = elapsed()

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

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `{s.get("starvation_shape")}`
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="G0 hydration starvation harness (#1058)")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    run_probe(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
