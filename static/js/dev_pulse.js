/** Dev Pulse — registry github + graded snippet cards (honest-empty). */
(function () {
  "use strict";

  var section = document.getElementById("section-dev-pulse");
  var list = document.getElementById("dev-pulse-list");
  var summary = document.getElementById("dev-pulse-summary");
  if (!section || !list) return;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function repoHost(url) {
    try {
      var u = new URL(url);
      return u.hostname.replace(/^www\./, "") + u.pathname.replace(/\/$/, "");
    } catch (e) {
      return url;
    }
  }

  function renderSummary(payload) {
    if (!summary || !payload || !payload.summary) return;
    var s = payload.summary;
    summary.textContent =
      (s.with_repo || 0) + " with public repo · " + (s.without_repo || 0) + " flagged";
    summary.hidden = false;
  }

  function renderRows(payload) {
    if (!payload || payload.data_available === false) {
      list.innerHTML =
        '<li class="sr-dev-pulse__empty">' +
        esc(payload && payload.message ? payload.message : "Dev pulse warming up.") +
        "</li>";
      return;
    }
    var rows = payload.subnets || [];
    if (!rows.length) {
      list.innerHTML = '<li class="sr-dev-pulse__empty">No subnets in registry yet.</li>';
      return;
    }
    list.innerHTML = rows
      .map(function (row) {
        var risk = row.risk_flag === "no_public_repo";
        var badge = risk
          ? '<span class="sr-dev-pulse__badge sr-dev-pulse__badge--risk">No public repo</span>'
          : '<span class="sr-dev-pulse__badge sr-dev-pulse__badge--ok">Public repo</span>';
        var repo = row.github
          ? '<a class="sr-dev-pulse__repo" href="' +
            esc(row.github) +
            '" target="_blank" rel="noopener noreferrer">' +
            esc(repoHost(row.github)) +
            "</a>"
          : '<span class="sr-dev-pulse__repo sr-dev-pulse__repo--missing">—</span>';
        return (
          '<li class="sr-dev-pulse__card sr-glow-live">' +
          '<div class="sr-dev-pulse__top">' +
          '<span class="sr-dev-pulse__name">' +
          esc(row.name || "SN" + row.netuid) +
          ' <span class="sr-dev-pulse__sn">SN' +
          esc(row.netuid) +
          "</span></span>" +
          badge +
          "</div>" +
          repo +
          '<p class="sr-dev-pulse__grade">' +
          esc(row.graded_snippet || "No graded call on this SN yet.") +
          "</p>" +
          "</li>"
        );
      })
      .join("");
  }

  function loadDevPulse() {
    var fetchJson = window.apiFetchJson
      ? window.apiFetchJson("/api/dev-radar?limit=12", 12000)
      : fetch("/api/dev-radar?limit=12", { headers: { Accept: "application/json" } }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        });
    fetchJson
      .then(function (payload) {
        renderSummary(payload);
        renderRows(payload);
      })
      .catch(function () {
        list.innerHTML =
          '<li class="sr-dev-pulse__empty">No registry economics — dev pulse warming up</li>';
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadDevPulse);
  } else {
    loadDevPulse();
  }
})();
