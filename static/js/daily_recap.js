/** §17.F4b — daily recap UI (yesterday briefing, textContent-safe HTML) */
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

  function block(title, id, body) {
    return (
      '<section class="weekly-letter__block" aria-labelledby="' +
      id +
      '">' +
      '<h3 class="weekly-letter__block-title" id="' +
      id +
      '">' +
      esc(title) +
      "</h3>" +
      body +
      "</section>"
    );
  }

  function renderPicks(rows) {
    rows = rows || [];
    if (!rows.length) {
      return '<p class="weekly-letter__note">No council picks recorded for yesterday.</p>';
    }
    var html = '<ul class="weekly-letter__list">';
    rows.forEach(function (p) {
      html +=
        '<li class="weekly-letter__item">' +
        '<span class="weekly-letter__item-name">' +
        esc(p.summary || "pick") +
        (p.action ? " · " + esc(String(p.action).toUpperCase()) : "") +
        "</span>" +
        (p.reason
          ? '<span class="weekly-letter__item-meta">' + esc(p.reason) + "</span>"
          : "") +
        "</li>";
    });
    html += "</ul>";
    return html;
  }

  function renderResolutions(rows, stats) {
    rows = rows || [];
    if (!rows.length) {
      return '<p class="weekly-letter__note">No gradeable resolutions yesterday.</p>';
    }
    var html =
      '<p class="weekly-letter__lead"><strong>' +
      String(stats.correct || 0) +
      "/" +
      String(stats.resolved_count || rows.length) +
      "</strong> direction hits</p>";
    html += '<ul class="weekly-letter__list">';
    rows.slice(0, 5).forEach(function (r) {
      html +=
        '<li class="weekly-letter__item">' +
        '<span class="weekly-letter__item-name">' +
        esc(r.name || "SN" + r.netuid) +
        "</span>" +
        '<span class="weekly-letter__item-meta">' +
        esc(r.outcome || "?") +
        " · pred " +
        esc(r.predicted_pct) +
        "% → " +
        esc(r.actual_pct) +
        "%</span></li>";
    });
    html += "</ul>";
    return html;
  }

  function renderSimpleList(rows, emptyMsg, labelKey) {
    rows = rows || [];
    if (!rows.length) return '<p class="weekly-letter__note">' + esc(emptyMsg) + "</p>";
    var html = '<ul class="weekly-letter__list">';
    rows.forEach(function (row) {
      var label = row[labelKey] || row.name || row.id || "item";
      var meta = row.regime
        ? row.regime + " · " + (row.outcome || "pending")
        : row.message || row.alert_type || "";
      html +=
        '<li class="weekly-letter__item">' +
        '<span class="weekly-letter__item-name">' +
        esc(label) +
        "</span>" +
        (meta ? '<span class="weekly-letter__item-meta">' + esc(meta) + "</span>" : "") +
        "</li>";
    });
    html += "</ul>";
    return html;
  }

  function render(root, payload) {
    if (!root) return;
    if (!payload || payload.status !== "ok") {
      root.innerHTML = '<p class="weekly-letter__empty">Daily recap unavailable right now.</p>';
      return;
    }
    if (payload.empty) {
      root.innerHTML =
        '<p class="weekly-letter__empty">Nothing to recap for yesterday yet — picks and grades populate as the council runs.</p>';
      return;
    }
    root.innerHTML =
      '<article class="weekly-letter__digest">' +
      block("Picks", "daily-recap-picks", renderPicks(payload.picks)) +
      block(
        "Resolutions",
        "daily-recap-resolutions",
        renderResolutions(payload.resolutions, payload.stats || {})
      ) +
      block(
        "Scenarios",
        "daily-recap-scenarios",
        renderSimpleList(payload.scenarios, "No scenarios recorded yesterday.", "name")
      ) +
      block(
        "Alerts",
        "daily-recap-alerts",
        renderSimpleList(payload.alerts, "No notable alerts yesterday.", "message")
      ) +
      "</article>";
  }

  async function hydrate() {
    var root = $("daily-recap-root");
    var dateEl = $("daily-recap-date");
    if (!root) return;
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    };
    try {
      var payload = await fetchJson("/api/letter/daily", 15000);
      if (dateEl && payload.date) {
        dateEl.textContent = "Recap for " + payload.date + " (UTC)";
      }
      render(root, payload);
      if (window.LetterExport && window.LetterExport.daily) {
        window.LetterExport.daily.setMarkdown(
          payload.markdown,
          "daily-recap-" + (payload.date || "export")
        );
      }
    } catch (e) {
      if (dateEl) dateEl.textContent = "Morning briefing";
      root.innerHTML =
        '<p class="weekly-letter__empty">Could not load daily recap — try again shortly.</p>';
      if (window.LetterExport && window.LetterExport.daily) {
        window.LetterExport.daily.setMarkdown("");
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrate);
  } else {
    hydrate();
  }
})();
