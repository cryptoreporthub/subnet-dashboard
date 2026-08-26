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


def test_run_starts_hero_before_trail_story_strip_evidence():
    js = HYDRATE.read_text(encoding="utf-8")
    run = js.split("async function run()")[1].split("async function runDeferredPanels")[0]
    await_at = run.index("await Promise.allSettled([dailyPickRequest, statsRequest])")
    assert run.index("kickPriorityPanels()") > await_at
    assert run.index("startTrailHydration()") > await_at
    assert "prefetchFocusJudges(dpResult)" in run[await_at:]
    assert run.index("storyStripUrl()") > await_at
    assert "armHeroCriticalRelease" in run
    assert "if (opts.force) invalidateDailyPickFetch()" in js
    assert "opts.force || tribunalHeroNeedsHydrate()) invalidateDailyPickFetch" not in js


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
