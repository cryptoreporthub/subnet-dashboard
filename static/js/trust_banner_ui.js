/** §21 L4 — trust banner binds /api/learning/stats trust_banner only (RF-2). */
(function () {
  "use strict";

  window.SimiLearning = window.SimiLearning || { stats: null, trust_banner: null };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderTrustBanner(tb) {
    var host = document.getElementById("home-trust-banner");
    if (!host || !tb) return;
    var ready = !!tb.ready;
    host.className = "trust-banner" + (ready ? " trust-banner--ready" : " trust-banner--blocked");

    var html = "";
    if (ready && tb.headline) {
      html += '<p class="trust-banner__headline">' + esc(tb.headline) + "</p>";
    } else if (tb.message) {
      html += '<p class="trust-banner__message">' + esc(tb.message) + "</p>";
    } else {
      html +=
        '<p class="trust-banner__message">Building graded track record — trust surfaces stay honest until sample clears.</p>';
    }
    if (tb.note) {
      html += '<p class="trust-banner__note">' + esc(tb.note) + "</p>";
    }
    host.innerHTML = html;
  }

  function cacheStats(stats, tb) {
    window.SimiLearning.stats = stats || null;
    window.SimiLearning.trust_banner = tb || null;
  }

  function applyPayload(payload) {
    if (!payload) return;
    var stats = payload.data || payload;
    var tb = stats.trust_banner;
    if (!tb && payload.trust_banner) {
      tb = payload.trust_banner;
      stats = Object.assign({}, stats, { trust_banner: tb });
    }
    if (tb) {
      cacheStats(stats, tb);
      renderTrustBanner(tb);
    }
  }

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      return r.ok ? r.json() : null;
    });
  }

  function loadTrustBanner() {
    fetchJson("/api/learning/stats")
      .then(function (payload) {
        if (payload) {
          applyPayload(payload);
          return;
        }
        return fetchJson("/api/learning-metrics");
      })
      .then(function (fallback) {
        if (fallback) applyPayload(fallback);
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadTrustBanner);
  } else {
    loadTrustBanner();
  }

  document.addEventListener("home:cockpit-tick", loadTrustBanner);

  window.SimiTrustBanner = { refresh: loadTrustBanner, render: renderTrustBanner };
})();
