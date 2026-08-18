/* SimiVision Listener — page JS (§28-3). Defensive: every fetch is guarded;
   the SSR render is the fallback. Nothing fake is ever shown. */
(function () {
  "use strict";

  var trust = document.getElementById("lsnTrust");
  if (!trust) return;

  /* ── trust strip: mode cycle (live / reconnecting / archive / warming) ── */
  var modes = [
    { m: "live", label: "LIVE", d: "M0,13 L20,13 L24,9 L28,17 L32,13 L55,13 L59,9 L63,17 L67,13 L90,13 L94,9 L98,17 L102,13 L120,13" },
    { m: "reconnecting", label: "RECONNECTING", d: "M0,13 L10,13 L14,6 L18,20 L22,11 L28,13 L36,13 L40,7 L44,19 L48,10 L56,13 L64,13 L68,6 L72,20 L76,11 L84,13 L92,13 L96,7 L100,19 L104,10 L120,13" },
    { m: "archive", label: "ARCHIVE", d: "M0,13 L120,13" },
    { m: "warming", label: "WARMING", d: "M0,13 L18,13 L22,10 L26,16 L30,13 L58,13 L62,10 L66,16 L70,13 L98,13 L102,10 L106,16 L110,13 L120,13" }
  ];
  var pollGeneration = 0;

  var modeBtn = document.getElementById("lsnModeBtn");
  var modeLabel = document.getElementById("lsnModeLabel");
  var ekg = document.getElementById("lsnEkg");
  var mi = 0;
  for (var i = 0; i < modes.length; i++) {
    if (modes[i].m === trust.getAttribute("data-mode")) { mi = i; break; }
  }
  if (modeBtn) {
    modeBtn.addEventListener("click", function () {
      mi = (mi + 1) % modes.length;
      var cur = modes[mi];
      trust.setAttribute("data-mode", cur.m);
      modeLabel.textContent = cur.label;
      ekg.setAttribute("d", cur.d);
    });
  }

  /* ── cal chip: reflect calibration endpoint when reachable ── */
  var calChip = document.getElementById("lsnCal");
  var calLabel = document.getElementById("lsnCalLabel");
  if (calChip) {
    calChip.addEventListener("click", function () {
      calChip.classList.toggle("drift");
      calLabel.textContent = calChip.classList.contains("drift") ? "cal ⚠ drift" : "cal ✓";
    });
    try {
      fetch("/api/message-intel/calibration", { headers: { "Accept": "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (j && j.active === false) {
            calChip.classList.add("drift");
            calLabel.textContent = "cal ⚠ drift";
          }
        })
        .catch(function () { /* keep SSR default — honest */ });
    } catch (e) { /* ignore */ }
  }

  /* ── share popover ── */
  var shareBtn = document.getElementById("lsnShareBtn");
  var sharePop = document.getElementById("lsnSharePop");
  if (shareBtn && sharePop) {
    shareBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var s = sharePop.classList.toggle("show");
      shareBtn.setAttribute("aria-expanded", s ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!sharePop.contains(e.target) && !shareBtn.contains(e.target)) {
        sharePop.classList.remove("show");
        shareBtn.setAttribute("aria-expanded", "false");
      }
    });
    var copyBtn = document.getElementById("lsnCopyBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var urlEl = sharePop.querySelector(".url");
        var text = (urlEl && urlEl.textContent.trim()) || window.location.href || "";
        var copyPromise = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text) : Promise.reject(new Error("clipboard unavailable"));
        copyPromise.then(function () { copyBtn.textContent = "Copied ✓"; copyBtn.classList.add("ok"); }).catch(function () { copyBtn.textContent = "Copy unavailable"; copyBtn.classList.remove("ok"); });
        setTimeout(function () { copyBtn.textContent = "Copy"; copyBtn.classList.remove("ok"); }, 1600);
      });
    }
  }

  /* ── quiet ── */
  var quietBtn = document.getElementById("lsnQuietBtn");
  if (quietBtn) {
    quietBtn.addEventListener("click", function () {
      document.body.classList.toggle("quiet");
      quietBtn.classList.toggle("on");
      quietBtn.textContent = document.body.classList.contains("quiet") ? "exit quiet" : "quiet?";
    });
  }

  /* ── net flow gauge: 60s pool-delta wiring ─────────────────────────────
     Honest contract: first poll establishes a baseline; the delta populates
     once a second sample exists. Pool taoLiquidity diffed between polls,
     signed. A TAO/USD rate is optional; without one, the gauge reports TAO
     flow rather than treating the subnet alpha price as a USD rate. Until
     two samples: "—" warming. */
  var anchorBtn = document.getElementById("lsnAnchorBtn");
  var anchorLabel = document.getElementById("lsnAnchorLabel");
  var picker = document.getElementById("lsnPicker");
  var rows = picker ? picker.querySelectorAll(".lsn-prow") : [];
  var gval = document.getElementById("lsnGval");
  var gdir = document.getElementById("lsnDir");
  var gbar = document.getElementById("lsnGbar");
  var gsub = document.getElementById("lsnGsub");
  var gpool = document.getElementById("lsnGpool");

  var anchor = null;
  var prevSample = null;
  var POLL_MS = 60000;

  function setAnchor(netuid, name) {
    if (!name && netuid) name = "SN" + netuid;
    anchor = { netuid: netuid, name: name || "—" };
    if (anchorLabel) anchorLabel.textContent = anchor.netuid ? "SN" + anchor.netuid : (anchor.name || "—");
    if (rows) rows.forEach(function (r) {
      r.classList.toggle("active", String(r.getAttribute("data-sn")) === String(netuid));
    });
  }

  function pickAnchor() {
    var msg = document.querySelector(".lsn-msg.focused");
    if (msg && msg.getAttribute("data-sn")) {
      setAnchor(msg.getAttribute("data-sn"), msg.getAttribute("data-name"));
      return;
    }
    var explicit = document.querySelector("[data-anchor=\"true\"]");
    if (explicit && explicit.getAttribute("data-sn")) {
      setAnchor(explicit.getAttribute("data-sn"), explicit.getAttribute("data-name"));
      return;
    }
    anchor = null;
    if (anchorLabel) anchorLabel.textContent = "—";
  }

  function fmtUsd(n) {
    if (n == null || isNaN(n)) return "—";
    var neg = n < 0;
    var abs = Math.abs(n);
    var s;
    if (abs >= 1000) s = "$" + (abs / 1000).toFixed(abs >= 100000 ? 0 : 1) + "K";
    else s = "$" + abs.toFixed(abs >= 100 ? 0 : 2);
    return (neg ? "−" : "+") + s;
  }

  function fmtTao(n) {
    if (n == null || isNaN(n)) return "—";
    var abs = Math.abs(n);
    var digits = abs >= 100 ? 0 : (abs >= 10 ? 1 : 2);
    return (n < 0 ? "−" : "+") + abs.toFixed(digits) + " TAO";
  }

  function poolChip(s) {
    if (!gpool || !s || s.tao == null || isNaN(s.tao)) return;
    if (s.rate) {
      var poolUsd = s.tao * s.rate;
      gpool.textContent = "$" + (poolUsd >= 1000 ? (poolUsd / 1000).toFixed(2) + "M" : poolUsd.toFixed(0)) + " pool";
    } else {
      gpool.textContent = s.tao.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " TAO pool";
    }
  }

  function warming(note) {
    gval.innerHTML = "— <small>· net flow</small>";
    gdir.textContent = "WARMING";
    gdir.className = "dir";
    gbar.style.width = "0";
    gsub.innerHTML = "<b>—</b> · " + (note || "awaiting pool snapshots");
    if (gpool) gpool.textContent = "—";
  }

  function applySample(s) {
    if (!anchor || !s || s.tao == null || isNaN(s.tao)) { warming(); return; }
    if (!prevSample) {
      prevSample = s;
      gsub.innerHTML = "<b>baseline set</b> · next poll computes the delta";
      poolChip(s);
      return;
    }
    var dTao = s.tao - prevSample.tao;
    var rate = s.rate || prevSample.rate || 0;
    var flow = dTao * rate;
    var dHold = (s.holders != null && prevSample.holders != null) ? s.holders - prevSample.holders : null;
    var pos = rate ? flow >= 0 : dTao >= 0;
    var label = pos ? "MONEY IN" : "MONEY OUT";
    var flowTxt = rate ? fmtUsd(flow) : fmtTao(dTao);
    gval.innerHTML = flowTxt + " <small>· 60s</small>";
    gdir.textContent = label;
    gdir.className = "dir " + (pos ? "pos" : "neg");
    var pct = Math.min(100, Math.max(8, (Math.abs(dTao) / Math.max(Math.abs(prevSample.tao) || 1, 1e-9)) * 1000));
    gbar.style.width = pct + "%";
    gbar.className = pos ? "" : "neg";
    var holdTxt = dHold == null ? "— holders" : (dHold >= 0 ? "+" + dHold : dHold) + " holders";
    gsub.innerHTML = "<b>" + holdTxt + "</b> · " + (s.holders != null ? s.holders.toLocaleString("en-US") + " total" : "");
     poolChip(s);
    prevSample = s;
  }

  function rowFromPayload(j) {
    if (Array.isArray(j)) return j[0] || null;
    if (!j || typeof j !== "object") return null;
    if (j.pool && typeof j.pool === "object") return j.pool;
    if (j.data && typeof j.data === "object") return j.data;
    if (Array.isArray(j.subnets)) return j.subnets[0] || null;
    if (Array.isArray(j.results)) return j.results[0] || null;
    return j;
  }

  function snapshotFromRow(row) {
    if (!row || typeof row !== "object") return null;
    var tao = parseFloat(
      row.taoLiquidity != null
        ? row.taoLiquidity
        : row.tao_liquidity != null
          ? row.tao_liquidity
          : row.pool_tao != null
            ? row.pool_tao
            : row.liquidity_tao != null
              ? row.liquidity_tao
              : row.total_tao != null
                ? row.total_tao
                : row.tao_reserve != null
                  ? row.tao_reserve
                  : NaN
    );
    var holders = parseInt(row.subnet_holders != null ? row.subnet_holders : row.holders, 10);
    var rate = parseFloat(
      /* row.price is the subnet alpha price, not a TAO/USD rate. */
      row.taoPriceUsd != null
        ? row.taoPriceUsd
        : row.tao_price_usd != null
          ? row.tao_price_usd
          : row.tao_usd_price != null
            ? row.tao_usd_price
            : row.taoUsd != null
              ? row.taoUsd
              : NaN
    );
    if (isNaN(tao)) return null;
    return { tao: tao, holders: isNaN(holders) ? null : holders, rate: isNaN(rate) ? 0 : rate };
  }

  function pollSubnets() {
    var generation = ++pollGeneration;
    try {
      if (!anchor) pickAnchor();
      if (!anchor || !anchor.netuid) { warming("select a subnet to inspect its pool"); return; }
      var endpoint = "/api/subnet/" + encodeURIComponent(anchor.netuid) + "/pool";
      fetch(endpoint, { headers: { "Accept": "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (generation !== pollGeneration) return;
          var row = rowFromPayload(j);
          if (!row && !anchor) { warming("pool snapshot unavailable — retrying"); return; }
          if (!row && anchor) { warming("pool snapshot unavailable — retrying"); return; }
          if (!anchor && row) setAnchor(row.netuid || row.id, row.name);
          var sample = snapshotFromRow(row);
          if (!sample) { warming("pool snapshot unavailable — retrying"); return; }
          applySample(sample);
        })
        .catch(function () { if (generation === pollGeneration) warming("pool feed unreachable — SSR state kept"); });
    } catch (e) { warming(); }
  }

  /* ── re-anchor on row / feed clicks ── */
  document.querySelectorAll(".lsn-trow, .lsn-crow2, .lsn-ylead, .lsn-yrow, .lsn-drow, .message-intel__sky-node, .message-intel__hc-cta[data-netuid], .message-intel__feed-row[data-netuid]").forEach(function (el) {
    el.addEventListener("click", function () {
      var sn = el.getAttribute("data-sn") || el.getAttribute("data-netuid");
      var nm = el.getAttribute("data-name");
      if (sn || nm) { setAnchor(sn, nm); prevSample = null; pollSubnets(); }
    });
  });

  /* ── anchor button + picker ── */
  if (anchorBtn && picker) {
    anchorBtn.addEventListener("click", function () {
      var s = picker.classList.toggle("show");
      anchorBtn.setAttribute("aria-expanded", s ? "true" : "false");
    });
    rows.forEach(function (r) {
      r.addEventListener("click", function () {
        rows.forEach(function (x) { x.classList.remove("active"); });
        r.classList.add("active");
        picker.classList.remove("show");
        anchorBtn.setAttribute("aria-expanded", "false");
        setAnchor(r.getAttribute("data-sn"), r.getAttribute("data-name"));
        prevSample = null;
        pollSubnets();
      });
    });
  }

  /* ── watchlist chips ── */
  document.querySelectorAll(".lsn-wchip[data-sn]").forEach(function (c) {
    c.addEventListener("click", function () {
      c.style.opacity = .35;
      c.style.pointerEvents = "none";
    });
  });


  /* ── share-page reaction crowns + hot-topic controls ──────────────── */
  function applyShareFeedFilter(next) {
    if (typeof window.__messageIntelSetFilter !== "function") return;
    window.__messageIntelSetFilter(next);
    var feed = document.getElementById("message-intel-feed");
    if (feed) feed.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  document.querySelectorAll(".lsn-topic").forEach(function (button) {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", function () {
      var topic = button.getAttribute("data-topic") || "";
      if (!topic) return;
      document.querySelectorAll(".lsn-topic").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
      button.setAttribute("aria-pressed", "true");
      applyShareFeedFilter({ topic: topic });
    });
  });
  document.querySelectorAll(".lsn-crow[data-author-id]").forEach(function (button) {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", function () {
      var authorId = button.getAttribute("data-author-id") || "";
      if (!authorId) return;
      document.querySelectorAll(".lsn-crow[data-author-id]").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
      button.setAttribute("aria-pressed", "true");
      applyShareFeedFilter({ authorId: authorId });
    });
  });
  /* ── boot + 60s poll ── */
  pickAnchor();
  pollSubnets();
  setInterval(pollSubnets, POLL_MS);
})();
