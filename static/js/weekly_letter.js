/** §17.F4 — weekly letter UI (structured JSON → HTML, XSS-safe) */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function pct(rate) {
    if (rate == null || isNaN(rate)) return "—";
    return (Number(rate) * 100).toFixed(1) + "%";
  }

  function fmtSigned(n) {
    var v = Number(n);
    if (isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  function renderTopPick(top) {
    top = top || {};
    var body = "";
    if (top.available && top.summary) {
      body +=
        '<p class="weekly-letter__lead"><strong>' +
        esc(top.summary) +
        "</strong>" +
        (top.action ? " · " + esc(String(top.action).toUpperCase()) : "") +
        "</p>";
      if (top.reason) body += '<p class="weekly-letter__note">' + esc(top.reason) + "</p>";
    } else if (top.held) {
      body += '<p class="weekly-letter__lead">No published long this period (honest HOLD / gate).</p>';
      if (top.reason) body += '<p class="weekly-letter__note">' + esc(top.reason) + "</p>";
      if (top.summary) {
        body += '<p class="weekly-letter__note">Candidate: ' + esc(top.summary) + "</p>";
      }
    } else {
      body += '<p class="weekly-letter__note">No top pick data yet.</p>';
    }
    return (
      '<section class="weekly-letter__block" aria-labelledby="weekly-letter-top-pick">' +
      '<h3 class="weekly-letter__block-title" id="weekly-letter-top-pick">Top pick</h3>' +
      body +
      "</section>"
    );
  }

  function renderWinRate(win) {
    win = win || {};
    var body = "";
    if (win.available) {
      body +=
        '<p class="weekly-letter__lead">Direction hit-rate: <strong>' +
        pct(win.win_pct) +
        "</strong> (" +
        String(win.win_count || 0) +
        "/" +
        String(win.total_closed || 0) +
        " closed)</p>";
      if (win.excess_vs_hold_tao_pct != null) {
        body +=
          '<p class="weekly-letter__note">Paper P&amp;L vs hold TAO: <strong>' +
          fmtSigned(win.excess_vs_hold_tao_pct) +
          "</strong></p>";
      }
    } else {
      body += '<p class="weekly-letter__note">No gradeable resolved picks yet.</p>';
    }
    return (
      '<section class="weekly-letter__block" aria-labelledby="weekly-letter-win-rate">' +
      '<h3 class="weekly-letter__block-title" id="weekly-letter-win-rate">Win rate</h3>' +
      body +
      "</section>"
    );
  }

  function renderScenarios(rows) {
    rows = rows || [];
    var body = "";
    if (!rows.length) {
      body = '<p class="weekly-letter__note">No scenarios recorded yet.</p>';
    } else {
      body = '<ul class="weekly-letter__list">';
      rows.forEach(function (s) {
        var label = s.name || s.id || "scenario";
        var regime = s.regime || "unknown";
        var outcome = s.outcome || "pending";
        body +=
          '<li class="weekly-letter__item">' +
          '<span class="weekly-letter__item-name">' +
          esc(label) +
          "</span>" +
          '<span class="weekly-letter__item-meta">' +
          esc(regime) +
          " · " +
          esc(outcome) +
          "</span>" +
          "</li>";
      });
      body += "</ul>";
    }
    return (
      '<section class="weekly-letter__block" aria-labelledby="weekly-letter-scenarios">' +
      '<h3 class="weekly-letter__block-title" id="weekly-letter-scenarios">Scenarios (≤3)</h3>' +
      body +
      "</section>"
    );
  }

  function render(root, payload) {
    if (!root) return;
    if (!payload || payload.status !== "ok") {
      root.innerHTML =
        '<p class="weekly-letter__empty">Weekly letter unavailable right now.</p>';
      return;
    }
    if (payload.empty) {
      root.innerHTML =
        '<p class="weekly-letter__empty">No letter content yet — picks, grades, and scenarios populate as the council runs.</p>';
      return;
    }
    root.innerHTML =
      '<article class="weekly-letter__digest">' +
      renderTopPick(payload.top_pick) +
      renderWinRate(payload.win_rate) +
      renderScenarios(payload.scenarios) +
      "</article>";
  }

  async function hydrate() {
    var root = $("weekly-letter-root");
    var weekEl = $("weekly-letter-week");
    if (!root) return;
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    };
    try {
      var payload = await fetchJson("/api/letter/weekly", 15000);
      if (weekEl && payload.week_of) {
        weekEl.textContent = "Week of " + payload.week_of;
      }
      render(root, payload);
      if (window.LetterExport && window.LetterExport.weekly) {
        window.LetterExport.weekly.setMarkdown(
          payload.markdown,
          "weekly-letter-" + (payload.week_of || "export")
        );
      }
    } catch (e) {
      if (weekEl) weekEl.textContent = "SimiVision digest";
      root.innerHTML =
        '<p class="weekly-letter__empty">Could not load weekly letter — try again shortly.</p>';
      if (window.LetterExport && window.LetterExport.weekly) {
        window.LetterExport.weekly.setMarkdown("");
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrate);
  } else {
    hydrate();
  }
})();
