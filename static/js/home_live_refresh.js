/**
 * §17.U4 — home hot-path live refresh (no full page reload).
 * Path: cockpit SSE tick → fetch daily-pick + predictions/resolved + subnets
 *       → patch #home-daily-call, #story-strip-body, #section-hero.
 * a11y: aria-live regions; focus preserved; polite updates only.
 */
(function () {
  "use strict";

  var REFRESH_MS = 60000;
  var CACHE_TTL_MS = 60000;
  var SKIP = { duplicate: 1, expired: 1, ungradeable: 1 };
  var busy = false;
  var lastRefreshAt = 0;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtSigned(n) {
    n = Number(n) || 0;
    return (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
  }

  function badgeClass(act) {
    act = String(act || "HOLD").toUpperCase();
    if (act === "BUY" || act === "LONG") return "badge-buy";
    if (act === "SELL" || act === "SHORT") return "badge-sell";
    return "badge-hold";
  }

  function fetchJson(url, ms) {
    ms = ms || 12000;
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      ctrl.abort();
    }, ms);
    return fetch(url, { signal: ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .catch(function (e) {
        clearTimeout(timer);
        throw e;
      });
  }

  function outcomeFromPred(pred) {
    if (pred.correct === true) return "correct";
    if (pred.correct === false) return "wrong";
    var actual = Number(pred.actual_pct);
    if (isNaN(actual)) return null;
    var dir = String(pred.direction || "").toLowerCase();
    if (dir === "up") return actual >= 0 ? "correct" : "wrong";
    if (dir === "down") return actual <= 0 ? "correct" : "wrong";
    return null;
  }

  function contextTags(pred) {
    var tags = [];
    var snap = pred.subnet_snapshot || {};
    if (snap.yield_trap) tags.push("yield trap");
    var driver = snap.return_driver || snap.dominant_driver;
    if (driver) tags.push(String(driver).replace(/_/g, " "));
    if (snap.price_change_7d != null && Math.abs(Number(snap.price_change_7d)) >= 1) {
      var v = Number(snap.price_change_7d);
      tags.push("price " + (v > 0 ? "up" : "down") + " " + Math.abs(v).toFixed(0) + "% 7d");
    }
    var signals = pred.active_signals;
    if (signals && signals.length) tags.push(String(signals[0]).replace(/_/g, " "));
    var out = [];
    tags.forEach(function (t) {
      if (t && out.indexOf(t) < 0) out.push(t);
    });
    return out.slice(0, 3);
  }

  function isTestFixture(pred) {
    var tags = pred.tags;
    if (tags && tags.length) {
      for (var i = 0; i < tags.length; i++) {
        var t = String(tags[i]).toUpperCase();
        if (t === "TEST_CASE" || t === "TEST" || t === "FIXTURE") return true;
      }
    }
    var stmt = String(pred.statement || "").toUpperCase();
    return stmt.indexOf("TEST_CASE") >= 0;
  }

  function buildStoryStrip(resolved, limit) {
    limit = limit || 8;
    var items = [];
    var rows = resolved || [];
    for (var i = rows.length - 1; i >= 0 && items.length < limit; i--) {
      var pred = rows[i];
      if (!pred || typeof pred !== "object") continue;
      if (SKIP[pred.outcome]) continue;
      if (isTestFixture(pred)) continue;
      if (pred.actual_pct == null) continue;
      var outcome = outcomeFromPred(pred);
      if (!outcome) continue;
      var netuid = pred.netuid;
      items.push({
        id: pred.id,
        netuid: netuid,
        name: pred.name || (netuid != null ? "SN" + netuid : "—"),
        predicted_pct: pred.predicted_pct,
        actual_pct: pred.actual_pct,
        outcome: outcome,
        statement: pred.statement,
        tags: contextTags(pred).filter(function (t) {
          var u = String(t).toUpperCase();
          return u !== "TEST_CASE" && u !== "TEST" && u !== "FIXTURE";
        }),
      });
    }
    var correct = items.filter(function (r) {
      return r.outcome === "correct";
    }).length;
    return {
      data_available: items.length > 0,
      reason: items.length ? null : "no_resolved_outcomes",
      items: items,
      stats: { correct: correct, wrong: items.length - correct },
    };
  }

  function patchHomeDailyCall(payload) {
    var host = document.getElementById("home-daily-call");
    if (!host || !payload) return;
    // K3-7 P0: never wipe SSR dossier — patch fields only or no-op
    if (document.getElementById("k3-dossier")) {
      if (window.__cockpitHome && typeof window.__cockpitHome.renderDailyPick === "function") {
        window.__cockpitHome.renderDailyPick(payload);
      }
      return;
    }
    var pick = payload.pick;
    var cand = payload.candidate;
    var sn = (pick && pick.subnet) || (cand && cand.subnet) || {};
    var act = String(payload.action || "HOLD").toUpperCase();
    if (act === "LONG") act = "BUY";
    var reasons = (pick && pick.reasons) || (cand && cand.reasons) || [];
    var why = reasons[0] || payload.reason || "";

    var html;
    if (pick && (sn.name != null || sn.netuid != null)) {
      html =
        '<div class="council-call home-job__call">' +
        '<div class="council-call__action"><span class="badge ' +
        badgeClass(act) +
        '">' +
        esc(act) +
        "</span></div>" +
        '<p class="council-call__name">' +
        esc(sn.name || "SN" + sn.netuid) +
        "</p>" +
        '<p class="council-call__meta">SN' +
        esc(sn.netuid) +
        (sn.symbol ? " · " + esc(sn.symbol) : "") +
        "</p>" +
        (why ? '<p class="home-job__why">We expect: ' + esc(why) + "</p>" : "") +
        "</div>";
    } else {
      html =
        '<div class="council-call council-call--hold home-job__call">' +
        '<div class="council-call__action"><span class="badge badge-hold">HOLD</span></div>';
      if (sn.name != null || sn.netuid != null) {
        html +=
          '<p class="council-call__name">' +
          esc(sn.name || "SN" + sn.netuid) +
          "</p>" +
          '<p class="council-call__meta">SN' +
          esc(sn.netuid) +
          (sn.symbol ? " · " + esc(sn.symbol) : "") +
          " · candidate only</p>";
      } else {
        html += '<p class="council-call__name">No audited long call</p>';
      }
      html +=
        '<p class="home-job__why">' +
        esc(why || "Council waits until confidence clears the audit gate.") +
        "</p></div>";
    }
    host.innerHTML = html;

    var pin = document.getElementById("habit-pin-btn");
    if (pin && sn.netuid != null) {
      pin.dataset.netuid = String(sn.netuid);
      pin.disabled = false;
      pin.removeAttribute("aria-disabled");
    }
    try {
      document.dispatchEvent(new CustomEvent("home-daily-call-updated"));
    } catch (e) {}
  }

  function patchStoryStrip(strip) {
    var body = document.getElementById("story-strip-body");
    if (!body || !strip) return;
    if (!strip.data_available || !strip.items || !strip.items.length) {
      body.innerHTML =
        '<p class="story-strip__empty" id="story-strip-empty">' +
        (strip.reason === "no_resolved_outcomes"
          ? "No graded pick outcomes yet — the strip fills as §16 resolution runs."
          : "Pick story unavailable right now.") +
        "</p>";
      return;
    }
    var stats = strip.stats || { correct: 0, wrong: 0 };
    var html =
      '<p class="story-strip__meta" id="story-strip-meta">' +
      stats.correct +
      " right · " +
      stats.wrong +
      " wrong</p>" +
      '<ol class="story-strip__list" id="story-strip-list">';
    strip.items.forEach(function (row) {
      html +=
        '<li class="story-strip__item story-strip__item--' +
        esc(row.outcome) +
        '"' +
        (row.id
          ? ' data-prediction-id="' +
            esc(row.id) +
            '" role="button" tabindex="0" title="Replay pick-time snapshot"'
          : "") +
        ">" +
        '<span class="story-strip__verdict" aria-label="' +
        esc(row.outcome) +
        '">' +
        (row.outcome === "correct" ? "✓" : "✗") +
        "</span>" +
        '<span class="story-strip__name">' +
        esc(row.name) +
        "</span>";
      if (row.predicted_pct != null && row.actual_pct != null) {
        html +=
          '<span class="story-strip__move">' +
          fmtSigned(row.predicted_pct) +
          " → " +
          fmtSigned(row.actual_pct) +
          "</span>";
      } else if (row.statement) {
        html +=
          '<span class="story-strip__move">' + esc(String(row.statement).slice(0, 48)) + "</span>";
      }
      if (row.tags && row.tags.length) {
        html += '<span class="story-strip__tags">';
        row.tags.forEach(function (tag) {
          html += '<span class="story-strip__tag">' + esc(tag) + "</span>";
        });
        html += "</span>";
      }
      if (row.share_page_url) {
        html +=
          '<button type="button" class="story-strip__share" data-share-url="' +
          esc(row.share_page_url) +
          '" aria-label="Copy share link" title="Copy share link">Copy link</button>';
      }
      html += "</li>";
    });
    html += "</ol>";
    body.innerHTML = html;
  }

  function patchHero(subnets, meta) {
    if (window.__cockpitHome && typeof window.__cockpitHome.renderHero === "function") {
      window.__cockpitHome.renderHero(subnets, meta);
    }
  }

  function cacheFresh() {
    var cache = window.HomeHydrateCache;
    return cache && cache.at && (Date.now() - cache.at) < CACHE_TTL_MS;
  }

  async function refreshHomeHotPath() {
    if (busy || document.documentElement.dataset.hydrate !== "1") return;
    if (!document.querySelector("[data-home-live]")) return;
    var now = Date.now();
    if (now - lastRefreshAt < 5000) return;
    busy = true;
    try {
      var cache = window.HomeHydrateCache;
      if (cacheFresh() && cache.dailyPick && cache.subnets) {
        patchHomeDailyCall(cache.dailyPick);
        if (cache.resolved) {
          patchStoryStrip(buildStoryStrip(cache.resolved));
        }
        patchHero(cache.subnets, cache.subnetsMeta || {});
        lastRefreshAt = now;
        return;
      }
      var results = await Promise.allSettled([
        fetchJson("/api/daily-pick"),
        fetchJson("/api/predictions/resolved"),
        fetchJson("/api/subnets?fields=id,netuid,name,price_change_24h,apy,staking_data,total_stake,stake,emission,source,live,sources"),
      ]);
      if (results[0].status === "fulfilled") patchHomeDailyCall(results[0].value);
      if (results[1].status === "fulfilled") {
        var resolved = (results[1].value.resolved) || [];
        patchStoryStrip(buildStoryStrip(resolved));
        if (window.HomeHydrateCache) window.HomeHydrateCache.resolved = resolved;
      }
      if (results[2].status === "fulfilled") {
        var subPayload = results[2].value || {};
        patchHero(subPayload.subnets || [], subPayload.meta || {});
        if (window.HomeHydrateCache) {
          window.HomeHydrateCache.subnets = subPayload.subnets || [];
          window.HomeHydrateCache.subnetsMeta = subPayload.meta || {};
          window.HomeHydrateCache.at = Date.now();
        }
      }
      lastRefreshAt = now;
    } catch (e) {
      console.warn("[home_live_refresh] tick failed", e);
    } finally {
      busy = false;
    }
  }

  function bindCockpitTick() {
    document.addEventListener("home:cockpit-tick", function () {
      refreshHomeHotPath();
    });
    setInterval(refreshHomeHotPath, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindCockpitTick);
  } else {
    bindCockpitTick();
  }

  window.HomeLiveRefresh = {
    patchStoryStrip: patchStoryStrip,
    patchHomeDailyCall: patchHomeDailyCall,
    buildStoryStrip: buildStoryStrip,
  };
})();
