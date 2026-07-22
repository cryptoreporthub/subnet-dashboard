/** §17.F3 — paper portfolio P&L vs hold TAO */
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

  function fmtSigned(n, digits) {
    digits = digits === undefined ? 1 : digits;
    var v = Number(n);
    if (isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(digits) + "%";
  }

  function pctWin(rate) {
    if (rate == null || isNaN(rate)) return "—";
    return (Number(rate) * 100).toFixed(0) + "%";
  }

  function pnlClass(n) {
    var v = Number(n) || 0;
    if (v > 0) return "paper-portfolio__val--pos";
    if (v < 0) return "paper-portfolio__val--neg";
    return "paper-portfolio__val--flat";
  }

  function renderSummary(summary) {
    summary = summary || {};
    var total = Number(summary.total_pnl_pct) || 0;
    var avg = Number(summary.avg_pnl_pct);
    if (isNaN(avg)) avg = summary.total_closed ? total / Number(summary.total_closed) : 0;
    var hold = Number(summary.hold_tao_pnl_pct) || 0;
    var excess = Number(summary.excess_vs_hold_tao_pct);
    if (isNaN(excess)) excess = total - hold;
    var extreme = Math.abs(total) > 200 || Math.abs(excess) > 200;
    var headline = extreme ? avg : total;
    var headlineLabel = extreme ? "Avg per graded call" : "Council P&amp;L";

    var html =
      '<div class="paper-portfolio__compare" role="group" aria-label="P&amp;L vs hold TAO">' +
      '<div class="paper-portfolio__kpi">' +
      '<span class="paper-portfolio__lbl">' + headlineLabel + '</span>' +
      '<span class="paper-portfolio__val ' +
      pnlClass(headline) +
      '">' +
      fmtSigned(headline) +
      "</span>" +
      "</div>" +
      '<div class="paper-portfolio__kpi paper-portfolio__kpi--bench">' +
      '<span class="paper-portfolio__lbl">Hold TAO</span>' +
      '<span class="paper-portfolio__val paper-portfolio__val--flat">' +
      fmtSigned(hold) +
      "</span>" +
      "</div>" +
      '<div class="paper-portfolio__kpi paper-portfolio__kpi--excess">' +
      '<span class="paper-portfolio__lbl">Excess vs TAO</span>' +
      '<span class="paper-portfolio__val ' +
      pnlClass(excess) +
      '">' +
      fmtSigned(excess) +
      "</span>" +
      "</div>" +
      "</div>" +
      '<p class="paper-portfolio__stats">' +
      pctWin(summary.win_pct) +
      " win · " +
      String(summary.total_closed || 0) +
      " closed" +
      (summary.open_positions ? " · " + summary.open_positions + " open" : "") +
      "</p>";
    if (extreme) {
      html +=
        '<p class="paper-portfolio__note">Sum of paper % moves is ' +
        fmtSigned(total) +
        " across " +
        String(summary.total_closed || 0) +
        " closed — not compounded dollar P&amp;L.</p>";
    }
    return html;
  }

  function openCue(row) {
    var dir = String((row && row.direction) || "").toLowerCase();
    if (dir === "down" || dir === "short" || dir === "sell") return "EXIT";
    if (dir === "up" || dir === "long" || dir === "buy") return "TAKE";
    return "HOLD";
  }

  function renderPositions(closed, open) {
    closed = closed || [];
    open = open || [];
    if (!closed.length && !open.length) return "";

    var html = "";
    if (closed.length) {
      html += '<ol class="paper-portfolio__list" aria-label="Recent closed positions">';
      closed.slice(-10).reverse().forEach(function (row) {
        var hit = row.direction_hit;
        var cls = hit ? "paper-portfolio__item--win" : "paper-portfolio__item--loss";
        html +=
          '<li class="paper-portfolio__item ' +
          cls +
          '">' +
          '<span class="paper-portfolio__verdict" aria-label="' +
          (hit ? "win" : "loss") +
          '">' +
          (hit ? "✓" : "✗") +
          "</span>" +
          '<span class="paper-portfolio__name">' +
          esc(row.name || "SN" + row.netuid) +
          "</span>" +
          '<span class="paper-portfolio__move">' +
          fmtSigned(row.pnl_pct) +
          " · actual " +
          fmtSigned(row.actual_pct) +
          "</span>" +
          "</li>";
      });
      html += "</ol>";
    }
    if (open.length) {
      html += '<ol class="paper-portfolio__list paper-portfolio__list--open" aria-label="Open positions">';
      open.slice(0, 10).forEach(function (row) {
        var cue = openCue(row);
        html +=
          '<li class="paper-portfolio__item paper-portfolio__item--open">' +
          '<span class="paper-portfolio__cue" aria-label="desk cue">' +
          esc(cue) +
          "</span>" +
          '<span class="paper-portfolio__name">' +
          esc(row.name || "SN" + row.netuid) +
          "</span>" +
          '<span class="paper-portfolio__move">' +
          esc(row.direction || "?") +
          (row.predicted_pct != null ? " · est " + fmtSigned(row.predicted_pct) : "") +
          "</span></li>";
      });
      html += "</ol>";
    }
    return html;
  }

  function render(root, payload) {
    if (!root) return;
    if (!payload || payload.status !== "ok") {
      if (!root.querySelector(".paper-portfolio__compare")) {
        root.innerHTML =
          '<p class="paper-portfolio__empty">Paper portfolio unavailable right now.</p>';
      }
      return;
    }
    if (payload.empty) {
      root.innerHTML =
        '<p class="paper-portfolio__empty">No council paper trades yet — P&amp;L appears after resolved picks are graded (§16).</p>';
      return;
    }
    root.innerHTML =
      renderSummary(payload.summary) +
      renderPositions(payload.closed_positions, payload.open_positions);
  }

  async function hydrate(payload) {
    var root = $("paper-portfolio-root");
    if (!root) return;
    try {
      var data = payload;
      if (!data) {
        if (window.apiFetchJsonRetry) {
          data = await window.apiFetchJsonRetry("/api/portfolio/status", 25000, 2);
        } else if (window.apiFetchJson) {
          data = await window.apiFetchJson("/api/portfolio/status", 25000);
        } else {
          var r = await fetch("/api/portfolio/status", { headers: { Accept: "application/json" } });
          if (!r.ok) throw new Error("HTTP " + r.status);
          data = await r.json();
        }
      }
      render(root, data);
    } catch (e) {
      if (!root.querySelector(".paper-portfolio__compare")) {
        root.innerHTML =
          '<p class="paper-portfolio__empty empty--quiet">Quiet — paper portfolio unavailable. Retry when /api/portfolio/status responds.</p>';
      }
    }
  }

  window.PaperPortfolio = { hydrate: hydrate, render: render };

  if (document.documentElement.dataset.hydrate !== "1") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { hydrate(); });
    } else {
      hydrate();
    }
  }
})();
