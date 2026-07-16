/** §19.M2 — social sentiment cards from live message-intel rollup */
(function () {
  "use strict";

  var root = document.getElementById("social-sentiment-root");
  if (!root) return;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function scoreClass(label) {
    var l = String(label || "neutral").toLowerCase();
    if (l === "bullish") return "pos";
    if (l === "bearish") return "neg";
    return "neu";
  }

  function renderRows(rows) {
    var html = '<div class="soc-grid">';
    rows.forEach(function (row) {
      var label = String(row.label || "neutral").toLowerCase();
      var pct = Math.round(Number(row.score || 0.5) * 100);
      html +=
        '<div class="card soc-card">' +
        '<div class="soc-head">' +
        '<span class="pick-name">' +
        esc(row.name || "SN" + row.netuid) +
        "</span>" +
        '<span class="soc-score ' +
        scoreClass(label) +
        '">' +
        esc(label.toUpperCase()) +
        "</span>" +
        "</div>" +
        '<div class="pick-meta">SN' +
        esc(row.netuid) +
        " · " +
        esc(row.mentions || 0) +
        " mentions</div>" +
        '<div class="conviction-bar mt-2"><div class="conviction-fill tier-lime" style="width:' +
        pct +
        '%;"></div></div>' +
        "</div>";
    });
    html += "</div>";
    return html;
  }

  function renderEmpty(listener) {
    listener = listener || {};
    if (listener.live) {
      return (
        '<div class="card card-muted"><p class="empty">Listener live — per-subnet sentiment ' +
        "cards populate when messages mention netuids.</p></div>"
      );
    }
    return (
      '<div class="card card-muted"><p class="empty">Social sentiment warming up — ' +
      "message intel or registry mentions will populate here.</p></div>"
    );
  }

  async function hydrate(force) {
    if (!force && root.querySelector(".soc-card")) return;
    try {
      var statusRes = await fetch("/api/message-intel/status");
      var status = statusRes.ok ? await statusRes.json() : null;
      var res = await fetch("/api/message-intel/social?limit=6");
      if (!res.ok) throw new Error("HTTP " + res.status);
      var payload = await res.json();
      if (payload.rows && payload.rows.length) {
        root.innerHTML = renderRows(payload.rows);
      } else if (!root.querySelector(".soc-grid")) {
        root.innerHTML = renderEmpty(status && status.listener);
      }
    } catch (e) {
      if (!root.querySelector(".soc-card") && !root.querySelector(".soc-grid")) {
        root.innerHTML =
          '<div class="card card-muted"><p class="empty">Social sentiment unavailable right now.</p></div>';
      }
    }
  }

  document.addEventListener("home:cockpit-tick", function () {
    hydrate(true);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrate);
  } else {
    hydrate();
  }
})();
