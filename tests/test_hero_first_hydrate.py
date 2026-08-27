"""#1058 step 2 — hero-first hydrate window (stats + daily-pick before secondaries)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from server import app

API_FETCH = Path("static/js/api_fetch.js")
HYDRATE = Path("static/js/cockpit_hydrate.js")
SCRIPTS = Path("templates/partials/premium/scripts.html")
LETTER_SCRIPTS = (
    Path("static/js/brain_letter.js"),
    Path("static/js/weekly_letter.js"),
    Path("static/js/daily_recap.js"),
    Path("static/js/premium_judges.js"),
)
MINDMAP_GRAPH = Path("static/js/mindmap_graph.js")
DATA_FRESHNESS = Path("static/js/data_freshness.js")
DEV_PULSE = Path("static/js/dev_pulse.js")

# Scripts whose <script defer> tag appears before api_fetch.js on the homepage.
PRE_API_FETCH_SELF_STARTERS = (
    DATA_FRESHNESS,
    DEV_PULSE,
    MINDMAP_GRAPH,
)

# #1058 stats-window occupants — initial self-start must wait on afterHeroCritical.
STATS_WINDOW_GATED = {
    Path("static/js/data_freshness.js"): ("/api/data-freshness", "startPollWhenHeroReady"),
    Path("static/js/ops_readiness_badge.js"): ("/api/ops/readiness", "startPollWhenHeroReady"),
    Path("static/js/subnet_integrations.js"): ("/api/subnet-integrations", "startPollWhenHeroReady"),
    Path("static/js/market_drivers_ui.js"): ("/api/market-drivers", "startRefreshWhenHeroReady"),
    Path("static/js/story_path_ui.js"): ("/api/mindmap/story-path", "startLoadWhenHeroReady"),
    Path("static/js/paper_portfolio.js"): ("/api/portfolio/status", "startHydrateWhenHeroReady"),
    Path("static/js/watchlist_alerts.js"): ("/api/watchlist", "startWatchlistWhenHeroReady"),
    Path("static/js/message_intel_feed.js"): ("/api/message-intel", "startFeedWhenHeroReady"),
    Path("static/js/council_polish.js"): ("/api/whales/flow-signals", "afterHeroCritical"),
    Path("static/js/dev_pulse.js"): ("/api/dev-radar", "startLoadWhenHeroReady"),
}


def test_after_hero_critical_gate_defined():
    js = API_FETCH.read_text(encoding="utf-8")
    assert "function afterHeroCritical" in js
    assert "function releaseHeroCritical" in js
    assert "global.afterHeroCritical = afterHeroCritical" in js
    assert "global.releaseHeroCritical = releaseHeroCritical" in js


def test_cockpit_hydrate_is_before_letters_and_judges():
    html = SCRIPTS.read_text(encoding="utf-8")
    assert html.count("cockpit_hydrate.js") == 1
    hydrate_at = html.index("cockpit_hydrate.js")
    assert html.index("api_fetch.js") < hydrate_at
    for name in (
        "brain_letter.js",
        "weekly_letter.js",
        "daily_recap.js",
        "premium_judges.js",
    ):
        assert hydrate_at < html.index(name), name


def test_letters_and_judges_wait_for_hero_gate():
    for path in LETTER_SCRIPTS:
        text = path.read_text(encoding="utf-8")
        assert "afterHeroCritical" in text, path
    brain = Path("static/js/brain_letter.js").read_text(encoding="utf-8")
    assert 'home-daily-call-updated' in brain
    listener = brain.split("home-daily-call-updated")[1].split("});")[0]
    assert "afterHeroCritical" in listener
    assert "afterHeroCritical(hydrate)" in brain


def test_mindmap_graph_waits_for_hero_gate():
    js = MINDMAP_GRAPH.read_text(encoding="utf-8")
    assert "afterHeroCritical" in js
    assert "function refreshGraphUngated" in js
    assert "function refreshGraph()" in js
    refresh = js.split("function refreshGraph()")[1].split("async function init()")[0]
    assert "window.afterHeroCritical(refreshGraphUngated)" in refresh
    assert "/api/mindmap/graph" in js
    hydrate = HYDRATE.read_text(encoding="utf-8")
    assert "/api/mindmap/graph" not in hydrate


def test_run_starts_hero_before_trail_story_strip_evidence():
    js = HYDRATE.read_text(encoding="utf-8")
    run = js.split("async function run()")[1].split("async function runDeferredPanels")[0]
    await_at = run.index("await Promise.allSettled([dailyPickRequest, statsRequest])")
    assert run.index("kickPriorityPanels()") > await_at
    assert run.index("startTrailHydration()") > await_at
    assert run.index("connectCockpitStream()") > await_at
    assert "prefetchFocusJudges(dpResult)" in run[await_at:]
    assert run.index("storyStripUrl()") > await_at
    assert "armHeroCriticalRelease" in run
    assert "if (opts.force) invalidateDailyPickFetch()" in js
    assert "opts.force || tribunalHeroNeedsHydrate()) invalidateDailyPickFetch" not in js
    pre_hero = run[:await_at]
    assert "connectCockpitStream()" not in pre_hero


def test_stats_window_occupants_gate_initial_fetch():
    for path, (api_path, gate_fn) in STATS_WINDOW_GATED.items():
        text = path.read_text(encoding="utf-8")
        assert api_path in text, path
        assert gate_fn in text, path
        assert "afterHeroCritical" in text, path
        if gate_fn == "afterHeroCritical":
            assert "afterHeroCritical(loadFlowSignals)" in text, path
        else:
            gate_block = text.split(f"function {gate_fn}")[1][:400]
            assert "afterHeroCritical" in gate_block, path


def test_cockpit_stream_gated_behind_hero_wait():
    js = HYDRATE.read_text(encoding="utf-8")
    assert "/api/cockpit/stream" in js
    run = js.split("async function run()")[1].split("async function runDeferredPanels")[0]
    await_at = run.index("await Promise.allSettled([dailyPickRequest, statsRequest])")
    stream_at = run.index("connectCockpitStream()")
    assert stream_at > await_at


def test_served_homepage_loads_hydrate_before_letters():
    import server as srv

    srv._prime_emergency_home_html()
    srv._warm_homepage_cache(None)
    with TestClient(app) as client:
        html = client.get("/").text
    if "dataset.hydrate" not in html and 'data-hydrate="1"' not in html:
        return
    hydrate_at = html.index("/static/js/cockpit_hydrate.js")
    assert html.index("/static/js/api_fetch.js") < hydrate_at
    assert hydrate_at < html.index("/static/js/brain_letter.js")
    assert hydrate_at < html.index("/static/js/premium_judges.js")
    assert "href=\"/api/pump-alerts\"" in html
    assert "/static/js/mindmap_graph.js" in html


def test_hero_gate_queues_until_release():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const ctx = {
  fetch: function () { return Promise.reject(new Error('no fetch')); },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
};
ctx.window = ctx;
ctx.global = ctx;
ctx.this = ctx;
vm.runInNewContext(fs.readFileSync('static/js/api_fetch.js', 'utf8'), ctx);
let ran = false;
ctx.afterHeroCritical(function () { ran = true; });
if (ran) throw new Error('waiter ran before release');
ctx.releaseHeroCritical();
if (!ran) throw new Error('waiter did not run after release');
let late = false;
ctx.afterHeroCritical(function () { late = true; });
if (!late) throw new Error('post-release waiter must run immediately');
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_api_fetch_self_starters_wait_for_dcl_then_gate():
    """Defer evaluate at interactive must not fetch before api_fetch.js loads."""
    gate_names = {
        DATA_FRESHNESS: "startPollWhenHeroReady",
        DEV_PULSE: "startLoadWhenHeroReady",
        MINDMAP_GRAPH: "refreshGraph",
    }
    for path in PRE_API_FETCH_SELF_STARTERS:
        text = path.read_text(encoding="utf-8")
        gate_fn = gate_names[path]
        gate_block = text.split(f"function {gate_fn}(")[1].split("function ")[0]
        assert "DOMContentLoaded" in gate_block, path
        assert (
            "document.readyState === 'complete'" in gate_block
            or 'document.readyState === "complete"' in gate_block
        ), path
        assert f"function {gate_fn}" in text, path


def test_data_freshness_fetch_queued_until_hero_release():
    """Prod order: data_freshness.js evaluates before api_fetch.js (scripts partial)."""
    script = r"""
const fs = require('fs');
const vm = require('vm');
const fetches = [];
const dcl = [];
const ctx = {
  fetch: function (url) {
    fetches.push(String(url));
    return Promise.resolve({
      ok: true,
      json: function () { return Promise.resolve({ sync_enabled: true, effective_source: 'blockmachine', subnet_count: 1 }); },
    });
  },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  setInterval: function () { return 0; },
  clearInterval: clearInterval,
  document: {
    readyState: 'interactive',
    getElementById: function (id) {
      if (id === 'dataFreshnessBadge') return { className: '', textContent: 'Loading', setAttribute: function () {} };
      if (id === 'liveFeedPill') return { className: '', innerHTML: '' };
      if (id === 'headerDataSource') return { textContent: 'cache' };
      return null;
    },
    addEventListener: function (ev, fn) { if (ev === 'DOMContentLoaded') dcl.push(fn); },
    removeEventListener: function (ev, fn) {
      if (ev !== 'DOMContentLoaded') return;
      const i = dcl.indexOf(fn);
      if (i >= 0) dcl.splice(i, 1);
    },
    visibilityState: 'visible',
  },
};
ctx.window = ctx;
(async function () {
  vm.runInNewContext(fs.readFileSync('static/js/data_freshness.js', 'utf8'), ctx);
  if (fetches.length) throw new Error('freshness fetched before api_fetch loaded: ' + fetches);
  vm.runInNewContext(fs.readFileSync('static/js/api_fetch.js', 'utf8'), ctx);
  dcl.slice().forEach(function (fn) { fn(); });
  if (fetches.length) throw new Error('freshness fetched before release: ' + fetches);
  ctx.releaseHeroCritical();
  for (let i = 0; i < 20; i++) {
    await new Promise(function (resolve) { setImmediate(resolve); });
    if (fetches.some(function (u) { return u.indexOf('/api/data-freshness') >= 0; })) break;
  }
  if (!fetches.some(function (u) { return u.indexOf('/api/data-freshness') >= 0; })) {
    throw new Error('freshness did not fetch after release: ' + JSON.stringify(fetches));
  }
  process.exit(0);
})().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_dev_pulse_fetch_queued_until_hero_release():
    """Prod order: dev_pulse.js body tag evaluates before api_fetch.js."""
    script = r"""
const fs = require('fs');
const vm = require('vm');
const fetches = [];
const dcl = [];
const section = { classList: { remove: function () {}, add: function () {} } };
const list = { innerHTML: '' };
const ctx = {
  fetch: function (url) {
    fetches.push(String(url));
    return Promise.resolve({
      ok: true,
      json: function () { return Promise.resolve({ status: 'success', subnets: [], summary: {} }); },
    });
  },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  AbortController: AbortController,
  document: {
    readyState: 'interactive',
    getElementById: function (id) {
      if (id === 'section-dev-pulse') return section;
      if (id === 'dev-pulse-list') return list;
      if (id === 'dev-pulse-summary') return { textContent: '', hidden: true };
      return null;
    },
    addEventListener: function (ev, fn) { if (ev === 'DOMContentLoaded') dcl.push(fn); },
    removeEventListener: function (ev, fn) {
      if (ev !== 'DOMContentLoaded') return;
      const i = dcl.indexOf(fn);
      if (i >= 0) dcl.splice(i, 1);
    },
  },
};
ctx.window = ctx;
(async function () {
  vm.runInNewContext(fs.readFileSync('static/js/dev_pulse.js', 'utf8'), ctx);
  if (fetches.length) throw new Error('dev pulse fetched before api_fetch loaded: ' + fetches);
  vm.runInNewContext(fs.readFileSync('static/js/api_fetch.js', 'utf8'), ctx);
  dcl.slice().forEach(function (fn) { fn(); });
  if (fetches.length) throw new Error('dev pulse fetched before release: ' + fetches);
  ctx.releaseHeroCritical();
  for (let i = 0; i < 20; i++) {
    await new Promise(function (resolve) { setImmediate(resolve); });
    if (fetches.some(function (u) { return u.indexOf('/api/dev-radar') >= 0; })) break;
  }
  if (!fetches.some(function (u) { return u.indexOf('/api/dev-radar') >= 0; })) {
    throw new Error('dev pulse did not fetch after release: ' + JSON.stringify(fetches));
  }
  process.exit(0);
})().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_mindmap_graph_fetch_queued_until_hero_release():
    """Prod order: mindmap_graph.js evaluates before api_fetch.js (body partial)."""
    script = r"""
const fs = require('fs');
const vm = require('vm');
const fetches = [];
const dcl = [];
const root = {
  dataset: { api: '/api/mindmap/graph' },
  querySelector: function () { return null; },
};
const ctx = {
  fetch: function (url) {
    fetches.push(String(url));
    return Promise.resolve({
      ok: true,
      json: function () { return Promise.resolve({ status: 'success', nodes: [], edges: [] }); },
    });
  },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  AbortSignal: { timeout: function () { return undefined; } },
  console: { warn: function () {}, error: function () {} },
  document: {
    readyState: 'interactive',
    getElementById: function (id) { return id === 'mindmap-graph-root' ? root : null; },
    addEventListener: function (ev, fn) { if (ev === 'DOMContentLoaded') dcl.push(fn); },
    removeEventListener: function (ev, fn) {
      if (ev !== 'DOMContentLoaded') return;
      const i = dcl.indexOf(fn);
      if (i >= 0) dcl.splice(i, 1);
    },
  },
};
ctx.window = ctx;
(async function () {
  vm.runInNewContext(fs.readFileSync('static/js/mindmap_graph.js', 'utf8'), ctx);
  if (fetches.length) throw new Error('graph fetched before api_fetch loaded: ' + fetches);
  vm.runInNewContext(fs.readFileSync('static/js/api_fetch.js', 'utf8'), ctx);
  dcl.slice().forEach(function (fn) { fn(); });
  if (fetches.length) throw new Error('graph fetched before release: ' + fetches);
  ctx.releaseHeroCritical();
  for (let i = 0; i < 20; i++) {
    await new Promise(function (resolve) { setImmediate(resolve); });
    if (fetches.some(function (u) { return u.indexOf('/api/mindmap/graph') >= 0; })) break;
  }
  if (!fetches.some(function (u) { return u.indexOf('/api/mindmap/graph') >= 0; })) {
    throw new Error('graph did not fetch after release: ' + JSON.stringify(fetches));
  }
})().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
