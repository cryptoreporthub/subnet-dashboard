/** §21 L1/L3 — market driver card + what's-working chips (API-driven, honest-empty). */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function riskClass(risk) {
    if (risk === "high") return "driver-card__risk--high";
    if (risk === "medium") return "driver-card__risk--med";
    return "driver-card__risk--low";
  }

  function renderDriverCard(payload) {
    var host = document.getElementById("home-driver-card");
    if (!host) return;
    if (!payload || payload.status !== "success") {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    var why = payload.why || [];
    var dec = payload.decomposition || {};
    var html =
      '<div class="driver-card__inner">' +
      '<p class="driver-card__headline">' +
      esc(payload.headline || "Market drivers") +
      "</p>";
    if (dec.staking_yield_apy != null) {
      html +=
        '<p class="driver-card__line">Staking APY ' +
        esc(Number(dec.staking_yield_apy).toFixed(1)) +
        "% <span class=\"driver-card__hint\">(income — not price)</span></p>";
    }
    if (dec.price_change_7d != null) {
      html +=
        '<p class="driver-card__line">Token price 7d: ' +
        esc(Number(dec.price_change_7d).toFixed(1)) +
        "%</p>";
    }
    if (dec.yield_trap) {
      html += '<p class="driver-card__warn">Yield trap — high APY but token falling</p>';
    }
    why.slice(0, 3).forEach(function (line) {
      html += '<p class="driver-card__why">' + esc(line) + "</p>";
    });
    html += "</div>";
    host.innerHTML = html;
    host.hidden = false;
  }

  function loadDriverCard(netuid) {
    var id = parseInt(String(netuid), 10);
    if (!id && id !== 0) return;
    fetch("/api/market-drivers/" + id)
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(renderDriverCard)
      .catch(function () {});
  }

  function renderWorkingChips(payload) {
    var host = document.getElementById("whats-working-chips");
    if (!host) return;
    if (!payload || !payload.top_price_signals || !payload.top_price_signals.length) {
      host.setAttribute("data-brain-state", "quiet");
      var graded = Number(payload && payload.graded_predictions) || 0;
      if (graded >= 50) {
        host.innerHTML =
          '<p class="whats-working__empty">' +
          graded +
          " graded — signal tags sparse on older picks; rankings fill as new calls resolve with stamps.</p>";
      } else {
        host.innerHTML =
          '<p class="whats-working__empty">Not enough graded picks yet to rank price signals.</p>';
      }
      return;
    }
    host.setAttribute("data-brain-state", "live");
    var html = "";
    payload.top_price_signals.slice(0, 5).forEach(function (row) {
      var pct = Math.round((row.hit_rate || 0) * 100);
      var n = row.n != null ? row.n : 0;
      html +=
        '<span class="whats-working__chip" title="' +
        esc(n + " picks graded on token price") +
        '">' +
        esc(row.signal || row.tag || "?") +
        " · n=" +
        esc(n) +
        " · " +
        pct +
        "%</span>";
    });
    host.innerHTML = html;
  }

  function loadWorkingChips() {
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; });
    };
    fetchJson("/api/market-drivers", 12000)
      .then(function (payload) {
        if (payload && payload.status === "success") {
          renderWorkingChips(payload);
        } else if (payload) {
          renderWorkingChips(payload);
        }
      })
      .catch(function () {
        var host = document.getElementById("whats-working-chips");
        if (!host) return;
        if (host.querySelector(".whats-working__chip")) return;
        host.setAttribute("data-brain-state", "quiet");
        host.innerHTML =
          '<p class="whats-working__empty">Quiet — signal rankings unavailable. Will retry after priority hydrate.</p>';
      });
  }

  function currentNetuid() {
    var pin = document.getElementById("habit-pin-btn");
    if (pin && pin.dataset.netuid) return pin.dataset.netuid;
    var call = document.querySelector(".council-call__meta");
    if (call && call.textContent) {
      var m = call.textContent.match(/SN(\d+)/);
      if (m) return m[1];
    }
    return null;
  }

  function refresh() {
    loadWorkingChips();
    loadDriverCard(currentNetuid());
  }

  if (document.documentElement.dataset.hydrate !== "1") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", refresh);
    } else {
      refresh();
    }
  }

  document.addEventListener("home-daily-call-updated", function () {
    loadDriverCard(currentNetuid());
  });

  window.SimiMarketDrivers = { refresh: refresh, loadDriverCard: loadDriverCard };
})();
