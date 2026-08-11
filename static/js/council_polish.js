/* Council final-polish (2026-08-11) — NET FLOW hero hydration.
   Reads /api/whales/flow-signals and renders into #cpol-netflow.
   Honest states: skeleton -> live -> warming-up empty. No inline scripts (CSP).
   Perf: __COUNCIL_PERF marks (measurement only) to verify preload/coalescing win. */
(function () {
  "use strict";
  var slot = document.getElementById("cpol-netflow");
  if (!slot) return;

  function mark(name) {
    try {
      var t = (window.performance && performance.now) ? Math.round(performance.now()) : Date.now();
      window.__COUNCIL_PERF = window.__COUNCIL_PERF || {};
      window.__COUNCIL_PERF[name] = t;
      if (window.__COUNCIL_PERF.t0) {
        window.__COUNCIL_PERF.deltaMs = Math.round(t - window.__COUNCIL_PERF.t0);
      }
    } catch (e) { /* measurement only */ }
  }
  mark("t0");

  function maybe(p) { return typeof p !== "undefined" && p !== null && p !== "" ? p : 0; }

  function fmtTao(v) {
    v = Number(v) || 0;
    var abs = Math.abs(v);
    if (abs >= 1000000) return (v / 1000000).toFixed(2) + "M τ";
    if (abs >= 1000) return (v / 1000).toFixed(1) + "k τ";
    return v.toFixed(0) + " τ";
  }

  function render(payload) {
    mark("t1_data");
    var available = payload && payload.status === "success";
    var sum = (payload && payload.summary) || {};
    var total = available ? (Number(sum.total_net_flow_tao) || 0) : null;

    if (!available || total === null) {
      slot.innerHTML = '' +
        '<div class="cpol-nf-kicker">NET FLOW · 24h — whale money in vs out</div>' +
        '<div class="cpol-empty"><b>Data warming up.</b> Whale ledger is still populating this cycle — the slot goes live as soon as flow signals land.</div>';
      return;
    }

    var cls = total > 0 ? "up" : (total < 0 ? "dn" : "flat");
    var trend = total >= 0 ? "▲" : "▼";
    var pills = [
      '<span class="cpol-chip">distribution <b>' + maybe(sum.distribution) + '</b></span>',
      '<span class="cpol-chip">accumulation <b>' + maybe(sum.accumulation) + '</b></span>',
      '<span class="cpol-chip">surges <b>' + maybe(sum.surges) + '</b></span>',
      '<span class="cpol-chip">flips <b>' + maybe(sum.flips) + '</b></span>',
      '<span class="cpol-chip mono">source <b>ledger</b></span>'
    ].join("");

    slot.innerHTML = '' +
      '<div class="cpol-nf-kicker">NET FLOW · 24h — whale money in vs out</div>' +
      '<div class="cpol-nf-main">' +
        '<div class="cpol-nf-value ' + cls + '">' + (total > 0 ? "+" : "") + fmtTao(total) + '</div>' +
        '<div class="cpol-nf-trend">' + trend + '</div>' +
      '</div>' +
      '<div class="cpol-nf-meta"><span>24h whale ledger across tracked wallets</span><span>in <b>' + fmtTao(sum.total_in || 0) + '</b> · out <b>' + fmtTao(sum.total_out || 0) + '</b></span></div>' +
      '<div class="cpol-nf-pills">' + pills + '</div>';
  }

  function fail() {
    mark("t1_fail");
    slot.innerHTML = '' +
      '<div class="cpol-nf-kicker">NET FLOW · 24h — whale money in vs out</div>' +
      '<div class="cpol-empty"><b>Signal unavailable right now.</b> Flow feed hit a snag — this clears on the next refresh cycle.</div>';
  }

  var api = slot.getAttribute("data-api") || "/api/whales/flow-signals?hours=24&limit=10";
  try {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", api, true);
    xhr.timeout = 6000;
    xhr.onload = function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { render(JSON.parse(xhr.responseText)); }
        catch (e) { fail(); }
      } else { fail(); }
    };
    xhr.onerror = fail;
    xhr.ontimeout = fail;
    xhr.send();
  } catch (e) { fail(); }
})();
