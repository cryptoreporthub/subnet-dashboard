/** §21 L4 — trust banner binds /api/learning/stats trust_banner only (RF-2). */
(function () {
  "use strict";

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

  function loadTrustBanner() {
    fetch("/api/learning/stats")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (payload) {
        var tb = (payload && payload.data && payload.data.trust_banner) || (payload && payload.trust_banner);
        if (tb) renderTrustBanner(tb);
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
