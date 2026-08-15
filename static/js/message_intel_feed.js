/** SS-TG W0–W3 — Subnet Summers Telegram desk */
(function () {
  "use strict";

  var feed = document.getElementById("message-intel-feed");
  var meta = document.getElementById("message-intel-meta");
  var sub = document.getElementById("message-intel-sub");
  var pulse = document.getElementById("message-intel-pulse");
  var groupLink = document.getElementById("message-intel-group-link");
  var trendingEl = document.getElementById("message-intel-trending");
  var championsEl = document.getElementById("message-intel-champions");
  var crownsEl = document.getElementById("message-intel-crowns");
  var weekTopEl = document.getElementById("message-intel-week-top");
  var refreshBtn = document.getElementById("message-intel-trending-refresh");
  var feedHint = document.getElementById("message-intel-feed-hint");
  var trendingTitle = document.getElementById("message-intel-trending-title");
  var trendingUnit = document.querySelector("#message-intel-trending-card .message-intel__panel-unit");
  var yesterdayCard = document.getElementById("message-intel-yesterday");
  var yesterdayLink = document.getElementById("message-intel-yesterday-link");
  var yesterdayStats = document.getElementById("message-intel-yesterday-stats");
  var yesterdayRunner = document.getElementById("message-intel-yesterday-runner");
  var yesterdayIcon = document.getElementById("message-intel-yesterday-icon");
  var yesterdayChips = document.getElementById("message-intel-yesterday-chips");
  var liveTag = document.getElementById("message-intel-live-tag");
  var hcStrip = document.getElementById("message-intel-hc-strip");
  var hcRows = document.getElementById("message-intel-hc-rows");
  var proofCard = document.getElementById("message-intel-proof");
  var proofBody = document.getElementById("message-intel-proof-body");
  var summary24hCard = document.getElementById("message-intel-summary-24h");
  var summary24hBody = document.getElementById("message-intel-summary-24h-body");
  var detailPanel = document.getElementById("message-intel-detail");
  var callersEl = document.getElementById("message-intel-callers");
  var callersBody = document.getElementById("message-intel-callers-body");
  var consensusBody = document.getElementById("message-intel-consensus-body");
  var divergenceBody = document.getElementById("message-intel-divergence-body");
  var convFiltersEl = document.getElementById("message-intel-conv-filters");
  var subnetFiltersEl = document.getElementById("message-intel-subnet-filters");
  var topicFiltersEl = document.getElementById("message-intel-topic-filters");
  if (!feed) return;

  var pulseRoot = document.querySelector(".message-intel--v2");

  function pulseModeFromHash() {
    var match = window.location.hash && window.location.hash.match(/^#pulse-(listen|learn|rank|serve)$/);
    return match ? match[1] : "listen";
  }

  function setPulseMode(mode, opts) {
    mode = /^(listen|learn|rank|serve)$/.test(mode) ? mode : "listen";
    opts = opts || {};
    if (!pulseRoot) return;
    pulseRoot.setAttribute("data-pulse-mode", mode);
    pulseRoot.querySelectorAll(".message-intel__loop [role='tab']").forEach(function (tab) {
      var active = tab.getAttribute("data-pulse-mode") === mode;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.setAttribute("tabindex", active ? "0" : "-1");
    });
    pulseRoot.querySelectorAll("[data-pulse-pane]").forEach(function (pane) {
      pane.hidden = pane.getAttribute("data-pulse-pane") !== mode;
    });
    if (!opts.hash) {
      try {
        window.history.replaceState(null, "", "#pulse-" + mode);
      } catch (e) {
        /* Hash navigation is progressive enhancement only. */
      }
    }
  }

  function bindPulseModes() {
    if (!pulseRoot) return;
    var tabs = Array.prototype.slice.call(pulseRoot.querySelectorAll(".message-intel__loop [role='tab']"));
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        setPulseMode(tab.getAttribute("data-pulse-mode") || "listen");
      });
    });
    var loop = pulseRoot.querySelector(".message-intel__loop");
    if (loop) {
      loop.addEventListener("keydown", function (event) {
        var direction = { ArrowLeft: -1, ArrowRight: 1, Home: "first", End: "last" }[event.key];
        if (direction == null || !tabs.length) return;
        var index = tabs.indexOf(document.activeElement);
        if (index < 0) index = tabs.findIndex(function (tab) {
          return tab.getAttribute("aria-selected") === "true";
        });
        var next = direction === "first"
          ? tabs[0]
          : direction === "last"
            ? tabs[tabs.length - 1]
            : tabs[(index + direction + tabs.length) % tabs.length];
        if (!next) return;
        event.preventDefault();
        next.focus();
        setPulseMode(next.getAttribute("data-pulse-mode") || "listen");
      });
    }
    setPulseMode(pulseModeFromHash(), { hash: true });
    window.addEventListener("hashchange", function () {
      setPulseMode(pulseModeFromHash(), { hash: true });
    });
  }

  var FILTER_KEY = "message-intel-filters";
  var WATCHLIST_KEY = "message-intel-watchlist";
  var filters = loadFilters();
  var watchlistState = loadWatchlistState();
  var latestTrendingRows = [];

  var lastStatus = null;
  var refreshTimer = null;
  var openDetailId = null;
  var GROUP_URL = "https://t.me/OfficialSubnetSummer";
  var callerDays = 30;

  function loadFilters() {
    try {
      var raw = sessionStorage.getItem(FILTER_KEY);
      if (raw) {
        var parsed = JSON.parse(raw);
        return {
          minConviction: parsed.minConviction != null ? Number(parsed.minConviction) : null,
          netuid: parsed.netuid != null ? Number(parsed.netuid) : null,
          topic: parsed.topic ? String(parsed.topic) : null,
        };
      }
    } catch (e) {
      /* ignore */
    }
    return { minConviction: 60, netuid: null, topic: null };
  }

  function saveFilters() {
    try {
      sessionStorage.setItem(FILTER_KEY, JSON.stringify(filters));
    } catch (e) {
      /* ignore */
    }
  }

  function loadWatchlistState() {
    try {
      var raw = localStorage.getItem(WATCHLIST_KEY);
      if (raw) {
        var parsed = JSON.parse(raw);
        return {
          netuids: Array.isArray(parsed.netuids) ? parsed.netuids.map(function (n) { return Number(n); }).filter(function (n) { return !isNaN(n) && n > 0; }) : [],
          thresholds: parsed.thresholds && typeof parsed.thresholds === "object" ? parsed.thresholds : {},
          hydrated: true,
          loading: false,
          upgrade: false,
        };
      }
    } catch (e) {
      /* ignore */
    }
    return { netuids: [], thresholds: {}, hydrated: false, loading: true, upgrade: false };
  }

  function saveWatchlistState() {
    try {
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify({
        netuids: watchlistState.netuids || [],
        thresholds: watchlistState.thresholds || {},
      }));
    } catch (e) {
      /* ignore */
    }
  }

  async function hydrateWatchlist() {
    try {
      var data = await fetchJsonWithRetry("/api/watchlist");
      if (data && data.status === "upgrade_required") {
        watchlistState.upgrade = true;
        watchlistState.loading = false;
        renderWatchlistPanel(latestTrendingRows);
        renderMyPulse(latestTrendingRows);
        bindWatchlistInteractions();
        return;
      }
      watchlistState.upgrade = false;
      watchlistState.netuids = (data.netuids || []).map(function (n) { return Number(n); }).filter(function (n) { return !isNaN(n) && n > 0; });
      watchlistState.hydrated = true;
      watchlistState.loading = false;
      saveWatchlistState();
    } catch (e) {
      watchlistState.loading = false;
    }
    try {
      var thresholds = await fetchJsonWithRetry("/api/watchlist/thresholds");
      watchlistState.thresholds = thresholds.thresholds || {};
      saveWatchlistState();
    } catch (e2) {
      /* keep local */
    }
    renderWatchlistPanel(latestTrendingRows);
    renderMyPulse(latestTrendingRows);
    bindWatchlistInteractions();
  }

  function buildListUrl(limit) {
    var url = "/api/message-intel?limit=" + encodeURIComponent(limit || 24);
    if (filters.minConviction != null) {
      url += "&min_conviction=" + encodeURIComponent(filters.minConviction);
    }
    if (filters.netuid != null) {
      url += "&netuid=" + encodeURIComponent(filters.netuid);
    }
    if (filters.topic) {
      url += "&topic=" + encodeURIComponent(filters.topic);
    }
    return url;
  }

  function syncFilterChipStates() {
    if (convFiltersEl) {
      convFiltersEl.querySelectorAll("[data-min-conv]").forEach(function (btn) {
        var val = btn.getAttribute("data-min-conv");
        var active =
          (val === "" && filters.minConviction == null) ||
          (val !== "" && Number(val) === filters.minConviction);
        btn.classList.toggle("message-intel__filter-chip--active", active);
      });
    }
    if (subnetFiltersEl) {
      subnetFiltersEl.querySelectorAll("[data-netuid]").forEach(function (btn) {
        var val = btn.getAttribute("data-netuid");
        var active =
          (val === "" && filters.netuid == null) ||
          (val !== "" && Number(val) === filters.netuid);
        btn.classList.toggle("message-intel__filter-chip--active", active);
      });
    }
    if (topicFiltersEl) {
      topicFiltersEl.querySelectorAll("[data-topic]").forEach(function (btn) {
        var val = btn.getAttribute("data-topic");
        var active =
          (val === "" && !filters.topic) || (val !== "" && val === filters.topic);
        btn.classList.toggle("message-intel__filter-chip--active", active);
      });
    }
  }

  function renderSubnetFilterChips(trending) {
    if (!subnetFiltersEl) return;
    var html =
      '<button type="button" class="message-intel__filter-chip' +
      (filters.netuid == null ? " message-intel__filter-chip--active" : "") +
      '" data-netuid="">All</button>';
    (trending || []).slice(0, 6).forEach(function (row) {
      if (row.netuid == null) return;
      var active = filters.netuid === Number(row.netuid) ? " message-intel__filter-chip--active" : "";
      html +=
        '<button type="button" class="message-intel__filter-chip' +
        active +
        '" data-netuid="' +
        esc(row.netuid) +
        '">SN' +
        esc(row.netuid) +
        "</button>";
    });
    subnetFiltersEl.innerHTML = html;
    bindFilterClicks();
  }

  function isWatchlisted(netuid) {
    return watchlistState.netuids.indexOf(Number(netuid)) !== -1;
  }

  function watchlistThreshold(netuid) {
    var t = watchlistState.thresholds || {};
    var raw = t[String(netuid)];
    return raw != null ? Number(raw) : null;
  }

  function watchlistToggleButton(netuid) {
    var on = isWatchlisted(netuid);
    return '<button type="button" class="message-intel__watch-toggle' + (on ? " is-on" : "") + '" data-watch-netuid="' + esc(netuid) + '">' + (on ? "Watching" : "Watch") + "</button>";
  }

  async function syncWatchlist() {
    try {
      await fetch("/api/watchlist", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ netuids: watchlistState.netuids || [] }),
      });
    } catch (e) {
      /* Browser-local state remains usable when the beta endpoint is unavailable. */
    }
  }

  async function saveWatchlistThreshold(netuid, rawValue) {
    var value = rawValue === "" ? null : Math.max(0, Math.min(100, Number(rawValue)));
    if (value !== null && isNaN(value)) return;
    watchlistState.thresholds[String(netuid)] = value;
    if (value === null) delete watchlistState.thresholds[String(netuid)];
    saveWatchlistState();
    try {
      await fetch("/api/watchlist/thresholds", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ netuid: Number(netuid), threshold: value }),
      });
    } catch (e) {
      /* Keep the local threshold until the backend is reachable. */
    }
    renderWatchlistPanel(latestTrendingRows);
    renderMyPulse(latestTrendingRows);
    bindWatchlistInteractions();
  }

  function bindWatchlistInteractions() {
    document.querySelectorAll("[data-watch-netuid]").forEach(function (button) {
      if (button.getAttribute("data-watch-bound") === "1") return;
      button.setAttribute("data-watch-bound", "1");
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        var netuid = Number(button.getAttribute("data-watch-netuid"));
        var idx = watchlistState.netuids.indexOf(netuid);
        if (idx === -1) watchlistState.netuids.push(netuid);
        else watchlistState.netuids.splice(idx, 1);
        watchlistState.netuids.sort(function (a, b) { return a - b; });
        saveWatchlistState();
        syncWatchlist();
        renderTrendingV2(latestTrendingRows, trendingUnit ? trendingUnit.textContent : "1h");
        renderWatchlistPanel(latestTrendingRows);
        renderMyPulse(latestTrendingRows);
        bindWatchlistInteractions();
      });
    });
    document.querySelectorAll("[data-watch-threshold]").forEach(function (input) {
      if (input.getAttribute("data-watch-threshold-bound") === "1") return;
      input.setAttribute("data-watch-threshold-bound", "1");
      input.addEventListener("change", function () {
        saveWatchlistThreshold(input.getAttribute("data-watch-threshold"), input.value);
      });
    });
    document.querySelectorAll("[data-watch-link]").forEach(function (button) {
      if (button.getAttribute("data-watch-link-bound") === "1") return;
      button.setAttribute("data-watch-link-bound", "1");
      button.addEventListener("click", async function () {
        var target = document.getElementById("message-intel-watch-link-code");
        if (target) target.textContent = "Generating…";
        try {
          var response = await fetchJsonWithRetry("/api/watchlist/link-code");
          if (target) target.textContent = "Send /link " + response.code + " to the Telegram bot.";
        } catch (e) {
          if (target) target.textContent = "Telegram linking is unavailable right now.";
        }
      });
    });
  }

  function bindFilterClicks() {
    if (convFiltersEl) {
      convFiltersEl.querySelectorAll("[data-min-conv]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var val = btn.getAttribute("data-min-conv");
          filters.minConviction = val === "" ? null : Number(val);
          saveFilters();
          syncFilterChipStates();
          hydrate();
        });
      });
    }
    if (subnetFiltersEl) {
      subnetFiltersEl.querySelectorAll("[data-netuid]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var val = btn.getAttribute("data-netuid");
          filters.netuid = val === "" ? null : Number(val);
          saveFilters();
          syncFilterChipStates();
          hydrate();
        });
      });
    }
    if (topicFiltersEl) {
      topicFiltersEl.querySelectorAll("[data-topic]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var val = btn.getAttribute("data-topic");
          filters.topic = val === "" ? null : val;
          saveFilters();
          syncFilterChipStates();
          hydrate();
        });
      });
    }
  }

  function renderFilterEmpty() {
    var parts = [];
    if (filters.minConviction != null) parts.push(filters.minConviction + "%+ conviction");
    if (filters.netuid != null) parts.push("SN" + filters.netuid);
    if (filters.topic) parts.push(filters.topic);
    var label = parts.length ? parts.join(" · ") : "current filters";
    return (
      '<p class="empty">No messages match ' +
      esc(label) +
      ". Try a lower conviction threshold or clear filters.</p>"
    );
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function openLivingFocus(netuid) {
    if (netuid == null) return;
    var root = document.getElementById("section-living-focus");
    if (root) {
      root.setAttribute("data-focus-netuid", String(netuid));
      root.scrollIntoView({ behavior: "smooth", block: "start" });
      document.dispatchEvent(
        new CustomEvent("living-focus:change", { detail: { netuid: Number(netuid) } })
      );
    }
  }

  function sentimentGaugeDeg(sentiment, avgConv) {
    var sent = String(sentiment || "cautious").toLowerCase();
    var conv =
      avgConv != null && !isNaN(Number(avgConv))
        ? Math.max(0, Math.min(100, Number(avgConv)))
        : 50;
    if (sent === "bullish") return 30 + (conv / 100) * 60;
    if (sent === "bearish") return 330 - (conv / 100) * 60;
    return 180;
  }

  function renderSentimentGauge(pulse, sentiment) {
    var avgConv = pulse.avg_conviction;
    var deg = sentimentGaugeDeg(sentiment, avgConv);
    var convLabel =
      avgConv != null && !isNaN(Number(avgConv))
        ? Math.round(Number(avgConv)) + "%"
        : "—";
    return (
      '<div class="message-intel__sent-gauge-wrap" aria-hidden="true">' +
      '<div class="message-intel__sent-gauge" style="--mi-sent-deg: ' +
      deg +
      'deg">' +
      '<div class="message-intel__sent-gauge-ring"></div>' +
      '<span class="message-intel__sent-gauge-core">' +
      esc(convLabel) +
      "</span></div></div>"
    );
  }

  function renderSummary24h(summary) {
    if (!summary24hCard || !summary24hBody) return;
    summary = summary || {};
    summary24hCard.hidden = false;
    if (!summary.ready) {
      summary24hBody.innerHTML =
        '<p class="message-intel__summary-24h-empty">' +
        esc(summary.empty_reason || "Not enough Telegram traffic in the last 24 hours yet.") +
        "</p>";
      return;
    }

    var pulse = summary.group_pulse || {};
    var sent = pulse.sentiment || "Cautious";
    var sentClass =
      sent.toLowerCase() === "bullish"
        ? "message-intel__sent--bull"
        : sent.toLowerCase() === "bearish"
          ? "message-intel__sent--bear"
          : "";
    var html =
      '<div class="message-intel__summary-24h-head">' +
      renderSentimentGauge(pulse, sent) +
      '<p class="message-intel__summary-24h-pulse"><b>' +
      esc(pulse.messages || summary.message_count || 0) +
      "</b> messages · <b>" +
      esc(summary.high_conviction_count != null ? summary.high_conviction_count : pulse.high_conviction || 0) +
      "</b> high conviction · <span class=\"" +
      sentClass +
      '">' +
      esc(sent) +
      "</span>" +
      (pulse.avg_conviction != null ? " · " + esc(pulse.avg_conviction) + "% avg conv" : "") +
      (pulse.group ? " · " + esc(pulse.group) : "") +
      "</p></div>";

    function chipRow(label, rows, kind) {
      if (!rows || !rows.length) return "";
      var chips = rows
        .map(function (row) {
          var netuid = row.netuid;
          var name = row.name || (netuid != null ? "SN" + netuid : "—");
          var deltaVal = row.change != null ? row.change : row.delta;
          var extra =
            kind === "mover" && deltaVal != null
              ? " " + (deltaVal > 0 ? "+" : "") + esc(deltaVal)
              : row.mentions != null
                ? " ×" + esc(row.mentions)
                : "";
          var cls =
            kind === "mover"
              ? deltaVal > 0
                ? " message-intel__summary-24h-chip--up"
                : deltaVal < 0
                  ? " message-intel__summary-24h-chip--down"
                  : ""
              : "";
          if (netuid == null) {
            return (
              '<span class="message-intel__summary-24h-chip' +
              cls +
              '">' +
              esc(name) +
              extra +
              "</span>"
            );
          }
          return (
            '<a class="message-intel__summary-24h-chip' +
            cls +
            '" href="/subnet/' +
            esc(netuid) +
            '">' +
            esc(name) +
            extra +
            "</a>"
          );
        })
        .join("");
      return (
        '<div class="message-intel__summary-24h-row">' +
        '<span class="message-intel__summary-24h-kicker">' +
        esc(label) +
        "</span>" +
        '<div class="message-intel__summary-24h-chips">' +
        chips +
        "</div></div>"
      );
    }

    html += chipRow("Top", summary.top_subnets || [], "top");
    html += chipRow("Movers", summary.movers || [], "mover");
    summary24hBody.innerHTML = html;
  }

  function renderTelegramProof(proof) {
    if (!proofCard || !proofBody) return;
    proof = proof || {};
    if (!proof.ready && !(proof.graded > 0)) {
      proofCard.hidden = true;
      proofBody.innerHTML = "";
      return;
    }
    proofCard.hidden = false;
    var rate = proof.hit_rate != null ? esc(proof.hit_rate) + "%" : "—";
    var html =
      '<p class="message-intel__proof-score"><b>' +
      rate +
      "</b> hit-rate · " +
      esc(proof.hits || 0) +
      "/" +
      esc(proof.graded || 0) +
      " graded Telegram calls</p>";
    if (proof.recent && proof.recent.length) {
      html += '<ul class="message-intel__proof-list">';
      proof.recent.forEach(function (r) {
        var label = r.status || (r.hit ? "hit" : "miss");
        html +=
          "<li><span class=\"message-intel__proof-" +
          label +
          '">' +
          esc(label.toUpperCase()) +
          "</span> " +
          esc(r.author_name || "anon") +
          (r.netuid != null ? " · SN" + esc(r.netuid) : "") +
          (r.move_pct != null || r.pump_pct_max != null ? " · " + esc(r.move_pct != null ? r.move_pct : r.pump_pct_max) + "% move" : "") +
          "</li>";
      });
      html += "</ul>";
    } else {
      html += '<p class="empty">Graded outcomes appear after price snapshots resolve.</p>';
    }
    proofBody.innerHTML = html;
  }

  function proofPill(proof) {
    proof = proof || {};
    if (!proof.eligible) return "";
    var status = String(proof.status || "pending").toLowerCase();
    var label = status === "pending" ? "Awaiting outcome" : status.toUpperCase();
    var move = proof.move_pct != null ? " · " + Number(proof.move_pct).toFixed(2) + "%" : "";
    return '<span class="message-intel__outcome message-intel__outcome--' + esc(status) + '">' + esc(label) + esc(move) + "</span>";
  }

  function renderCallerLeaderboard(payload) {
    if (!callersBody) return;
    payload = payload || {};
    if (payload.status === "upgrade_required") {
      callersBody.innerHTML = '<p class="empty">' + esc((payload.upgrade_prompt && payload.upgrade_prompt.body) || "Upgrade required.") + '</p>';
      return;
    }
    var callers = payload.callers || [];
    if (!callers.length) {
      callersBody.innerHTML = '<p class="empty">No resolved qualifying Telegram calls in this window yet. A caller needs explicit direction, 60%+ conviction, and a tracked price snapshot.</p>';
      return;
    }
    var html = '<p class="message-intel__caller-note">Accuracy excludes neutral moves and all engagement data. Minimum sample: ' + esc(payload.minimum_sample || 3) + ' resolved calls.</p><div class="message-intel__caller-list">';
    callers.forEach(function (row, index) {
      var name = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : row.author_name || "Unknown";
      var accuracy = row.accuracy != null ? row.accuracy + "%" : "—";
      html += '<article class="message-intel__caller-row' + (row.qualified ? "" : " is-provisional") + '">' +
        '<span class="message-intel__caller-rank">' + esc(index + 1) + '</span><div class="message-intel__caller-main"><b>' + esc(name) + '</b>' +
        '<span>' + esc(row.hits) + ' hit · ' + esc(row.misses) + ' miss · ' + esc(row.neutral) + ' neutral · n=' + esc(row.sample_size) + '</span></div>' +
        '<strong>' + esc(accuracy) + '</strong>' +
        '<button type="button" class="message-intel__receipt-toggle" data-caller-id="' + esc(row.author_id) + '" data-caller-name="' + esc(name) + '">' + (row.qualified ? "Receipts" : "Provisional receipts") + "</button></article>";
    });
    html += "</div><p class=\"message-intel__caller-disclaimer\">" + esc(payload.disclaimer || "Not financial advice.") + "</p>";
    callersBody.innerHTML = html;
    callersBody.querySelectorAll("[data-caller-id]").forEach(function (button) {
      button.addEventListener("click", function () {
        loadCallerReceipts(button.getAttribute("data-caller-id"), button.getAttribute("data-caller-name"));
      });
    });
  }

  async function loadCallerReceipts(authorId, name) {
    if (!callersBody) return;
    callersBody.insertAdjacentHTML("beforeend", '<div class="message-intel__receipts" id="message-intel-receipts"><p class="empty">Loading proof receipts for ' + esc(name) + "…</p></div>");
    var target = document.getElementById("message-intel-receipts");
    try {
      var data = await fetchJsonWithRetry("/api/message-intel/callers/" + encodeURIComponent(authorId) + "/receipts?days=" + callerDays + "&limit=20");
      var receipts = data.receipts || [];
      if (!receipts.length) {
        target.innerHTML = '<p class="empty">No resolved qualifying receipts in this window.</p>';
        return;
      }
      target.innerHTML = '<h4>Proof receipts · ' + esc(name) + '</h4>' + receipts.map(function (r) {
        var proof = r.proof || {};
        return '<button type="button" class="message-intel__receipt" data-receipt-id="' + esc(r.message_id) + '">' +
          proofPill(proof) + '<span>' + esc(snippet(r.content, 110)) + '</span><small>' + esc(fmtTime(r.timestamp)) + (r.netuid != null ? " · SN" + esc(r.netuid) : "") + "</small></button>";
      }).join("");
      target.querySelectorAll("[data-receipt-id]").forEach(function (button) {
        button.addEventListener("click", function () { toggleMessageDetail(button.getAttribute("data-receipt-id")); });
      });
    } catch (e) {
      target.innerHTML = '<p class="empty">Could not load these proof receipts.</p>';
    }
  }

  async function hydrateCallerLeaderboard() {
    if (!callersBody) return;
    callersBody.setAttribute("aria-busy", "true");
    try {
      var data = await fetchJsonWithRetry("/api/message-intel/callers?days=" + callerDays + "&limit=12");
      renderCallerLeaderboard(data);
    } catch (e) {
      callersBody.innerHTML = '<p class="empty">Caller proof is temporarily unavailable.</p>';
    } finally {
      callersBody.setAttribute("aria-busy", "false");
    }
  }

  function renderConsensus(payload) {
    if (!consensusBody) return;
    if (payload && payload.status === "upgrade_required") {
      consensusBody.innerHTML = '<p class="empty">' + esc((payload.upgrade_prompt && payload.upgrade_prompt.body) || "Upgrade required.") + '</p>';
      return;
    }
    var items = (payload && payload.items) || [];
    if (!items.length) {
      consensusBody.innerHTML = '<p class="empty">No evidence-qualified current Telegram calls yet. This stays empty until callers have resolved history and fresh directional calls.</p>';
      return;
    }
    consensusBody.innerHTML = '<div class="message-intel__consensus-list">' + items.map(function (row) {
      var state = row.ready ? String(row.label || "mixed") : "insufficient";
      var score = row.ready ? (Number(row.score) > 0 ? "+" : "") + Math.round(Number(row.score)) : "—";
      var calls = row.current_calls || [];
      var receipts = row.resolved_receipts || [];
      var current = calls.map(function (call) {
        var who = call.author_username ? "@" + String(call.author_username).replace(/^@/, "") : call.author_name;
        return '<button type="button" class="message-intel__consensus-receipt" data-receipt-id="' + esc(call.message_id) + '">' +
          '<b>' + esc(String(call.direction).toUpperCase()) + '</b> ' + esc(who) + ' · ' + esc(call.jury_conviction) + '% jury · ' + esc(call.author_accuracy) + '% proven</button>';
      }).join("");
      var resolved = receipts.map(function (receipt) {
        return '<button type="button" class="message-intel__consensus-receipt" data-receipt-id="' + esc(receipt.message_id) + '">' + proofPill(receipt.proof) + esc(snippet(receipt.content, 74)) + '</button>';
      }).join("");
      return '<article class="message-intel__consensus-row message-intel__consensus-row--' + esc(state) + '">' +
        '<div class="message-intel__consensus-head"><a href="/subnet/' + esc(row.netuid) + '"><b>' + esc(row.name) + '</b> <span>SN' + esc(row.netuid) + '</span></a>' +
        '<strong>' + esc(row.ready ? String(row.label).toUpperCase() + ' ' + score : "INSUFFICIENT DATA") + '</strong></div>' +
        '<p>' + esc(row.call_count) + ' current calls · ' + esc(row.contributor_count) + ' proven contributors' +
        (row.ready ? ' · bounded score ' + esc(score) + '/100' : ' · ' + esc(row.insufficient_reason || "") ) + '</p>' +
        '<details><summary>Inspect ' + esc(calls.length) + ' current calls and ' + esc(receipts.length) + ' resolved receipts</summary>' +
        '<div class="message-intel__consensus-receipts"><p>Current calls</p>' + (current || '<span>No current calls.</span>') +
        '<p>Resolved-call receipts</p>' + (resolved || '<span>No matching resolved receipts available.</span>') + '</div></details></article>';
    }).join("") + '</div><p class="message-intel__caller-disclaimer">Telegram consensus is evidence-qualified community commentary, not investment advice.</p>';
    consensusBody.querySelectorAll("[data-receipt-id]").forEach(function (button) {
      button.addEventListener("click", function () { toggleMessageDetail(button.getAttribute("data-receipt-id")); });
    });
  }

  async function hydrateConsensus() {
    if (!consensusBody) return;
    try {
      renderConsensus(await fetchJsonWithRetry("/api/message-intel/subnet-conviction?limit=8"));
    } catch (e) {
      consensusBody.innerHTML = '<p class="empty">Evidence-weighted Telegram consensus is temporarily unavailable.</p>';
    }
  }

  function renderDivergence(payload) {
    if (!divergenceBody) return;
    if (payload && payload.status === "upgrade_required") {
      divergenceBody.innerHTML = '<p class="empty">' + esc((payload.upgrade_prompt && payload.upgrade_prompt.body) || "Upgrade required.") + '</p>';
      return;
    }
    var stories = (payload && payload.stories) || [];
    if (!stories.length) {
      divergenceBody.innerHTML = '<p class="empty">No resolved, evidence-qualified Telegram outcome stories in this window yet. Pending calls stay out until their recorded outcomes resolve.</p>';
      return;
    }
    divergenceBody.innerHTML = '<div class="message-intel__divergence-list">' + stories.map(function (story) {
      var state = String(story.state || "insufficient_data");
      var label = story.ready ? String(story.label || "mixed-evidence").replace(/-/g, " ").toUpperCase() : "INSUFFICIENT DATA";
      var window = story.time_window || {};
      var move = story.observed_move_pct != null ? (Number(story.observed_move_pct) > 0 ? "+" : "") + Number(story.observed_move_pct).toFixed(2) + "%" : "move unavailable";
      var receipts = story.receipts || [];
      var receiptHtml = receipts.map(function (receipt) {
        var proof = receipt.proof || {};
        return '<button type="button" class="message-intel__divergence-receipt" data-receipt-id="' + esc(receipt.message_id) + '">' +
          proofPill(proof) + '<span>' + esc(String(receipt.direction || "—").toUpperCase()) + ' → ' + esc(String(receipt.outcome_direction || "—").toUpperCase()) + ' · ' + esc(snippet(receipt.content, 86)) + '</span></button>';
      }).join("");
      var facts = story.ready
        ? 'Consensus <b>' + esc(String(story.consensus_direction || "mixed").toUpperCase()) + '</b> · observed <b>' + esc(String(story.observed_direction || "unavailable").toUpperCase()) + '</b> · ' + esc(move)
        : esc(story.insufficient_reason || "More resolved qualifying calls are needed.");
      return '<article class="message-intel__divergence-row message-intel__divergence-row--' + esc(state) + '">' +
        '<div class="message-intel__divergence-head"><a href="/subnet/' + esc(story.netuid) + '"><b>' + esc(story.name) + '</b> <span>SN' + esc(story.netuid) + '</span></a><strong>' + esc(label) + '</strong></div>' +
        '<p>' + facts + '</p><p class="message-intel__divergence-meta">' + esc(story.qualifying_call_count || 0) + ' qualifying calls · ' + esc(story.contributor_count || 0) + ' contributors · 24h outcomes' + (window.start ? ' · window ' + esc(fmtTime(window.start)) + (window.end ? ' to ' + esc(fmtTime(window.end)) : '') : '') + '</p>' +
        '<details><summary>Inspect ' + esc(receipts.length) + ' Telegram receipts</summary><div class="message-intel__divergence-receipts">' + (receiptHtml || '<span>No resolved receipts available.</span>') + '</div></details>' +
        '<p class="message-intel__divergence-caveat">' + esc(story.caveat || "Observed outcomes are not causal evidence.") + '</p></article>';
    }).join("") + '</div>';
    divergenceBody.querySelectorAll("[data-receipt-id]").forEach(function (button) {
      button.addEventListener("click", function () { toggleMessageDetail(button.getAttribute("data-receipt-id")); });
    });
  }

  async function hydrateDivergence() {
    if (!divergenceBody) return;
    try {
      renderDivergence(await fetchJsonWithRetry("/api/message-intel/divergence?days=7&limit=6"));
    } catch (e) {
      divergenceBody.innerHTML = '<p class="empty">Telegram outcome stories are temporarily unavailable.</p>';
    }
  }

  function renderHighConvictionStrip(rows) {
    if (!hcStrip || !hcRows) return;
    if (!rows || !rows.length) {
      hcStrip.hidden = true;
      hcRows.innerHTML = "";
      return;
    }
    hcStrip.hidden = false;
    hcRows.innerHTML = rows
      .map(function (row) {
        var verdict = row.verdict && typeof row.verdict === "object" ? row.verdict : {};
        var conv = row.conviction != null
          ? Math.round(Number(row.conviction))
          : verdict.conviction != null
            ? Math.round(Number(verdict.conviction))
            : "—";
        var netuid = row.netuid;
        if (netuid == null) {
          var match = String(row.content || "").match(/\b(?:sn|subnet)\s*#?\s*(\d{1,4})\b/i);
          netuid = match ? Number(match[1]) : null;
        }
        var sn = row.subnet_name || (netuid != null ? "SN" + netuid : "");
        return (
          '<div class="message-intel__hc-row">' +
          '<span class="message-intel__hc-conv">' +
          esc(conv) +
          "%</span>" +
          '<span class="message-intel__hc-snippet">' +
          esc(snippet(row.content, 48)) +
          "</span>" +
          (netuid != null
            ? '<button type="button" class="message-intel__hc-cta" data-netuid="' +
              esc(netuid) +
              '">Open SN' +
              esc(netuid) +
              "</button>"
            : "") +
          '<button type="button" class="message-intel__hc-cta message-intel__hc-cta--lf" data-lf-netuid="' +
          esc(netuid || "") +
          '" data-msg-id="' +
          esc(row.id) +
          '">Living Focus</button>' +
          "</div>"
        );
      })
      .join("");
    hcRows.querySelectorAll("[data-netuid]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        window.location.href = "/subnet/" + btn.getAttribute("data-netuid");
      });
    });
    hcRows.querySelectorAll("[data-lf-netuid]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var nu = btn.getAttribute("data-lf-netuid");
        if (nu) openLivingFocus(nu);
        else {
          var mid = btn.getAttribute("data-msg-id");
          if (mid) toggleMessageDetail(mid);
        }
      });
    });
  }

  function renderDetailPanel(detail, message) {
    if (!detailPanel) return;
    detail = detail || {};
    message = message || {};
    var outcome = detail.price_outcome || {};
    var snap = detail.price_snapshot || {};
    var graded = detail.graded;
    var proof = detail.proof || message.proof || {};
    var html =
      '<div class="message-intel__detail-card">' +
      '<button type="button" class="message-intel__detail-close" id="message-intel-detail-close">Close</button>' +
      '<p class="message-intel__detail-text">' +
      esc(message.content || "") +
      "</p>";
    if (detail.reasoning) {
      html +=
        '<p class="message-intel__detail-reason"><b>Verdict:</b> ' + esc(detail.reasoning) + "</p>";
    }
    if (snap && snap.tao_usd_price != null) {
      html +=
        '<p class="message-intel__detail-snap">Price at message: <b>' +
        esc(snap.tao_usd_price) +
        "</b>" +
        (snap.netuid != null ? " · SN" + esc(snap.netuid) : "") +
        "</p>";
    }
    if (graded && outcome.outcome) {
      html +=
        '<p class="message-intel__detail-outcome"><b>Outcome:</b> ' +
        esc(outcome.outcome) +
        (outcome.pump_pct_max != null ? " · " + esc(outcome.pump_pct_max) + "% max move" : "") +
        "</p>";
    } else if (proof.eligible) {
      html += '<p class="message-intel__detail-outcome message-intel__detail-outcome--pending">Outcome pending — grading runs every ~5 min.</p>';
    }
    if (proof.eligible) html += '<p class="message-intel__detail-proof">Proof: ' + proofPill(proof) + ' · resolved qualifying calls only; not financial advice.</p>';
    if (detail.netuid != null) {
      html +=
        '<div class="message-intel__detail-actions">' +
        '<a class="message-intel__hc-cta" href="/subnet/' +
        esc(detail.netuid) +
        '">Open SN' +
        esc(detail.netuid) +
        "</a>" +
        '<button type="button" class="message-intel__hc-cta message-intel__hc-cta--lf" id="message-intel-detail-lf">Living Focus</button>' +
        "</div>";
    }
    html += "</div>";
    detailPanel.innerHTML = html;
    detailPanel.hidden = false;
    var closeBtn = document.getElementById("message-intel-detail-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        detailPanel.hidden = true;
        openDetailId = null;
      });
    }
    var lfBtn = document.getElementById("message-intel-detail-lf");
    if (lfBtn && detail.netuid != null) {
      lfBtn.addEventListener("click", function () {
        openLivingFocus(detail.netuid);
      });
    }
  }

  async function toggleMessageDetail(msgId) {
    if (!detailPanel) return;
    if (openDetailId === String(msgId)) {
      detailPanel.hidden = true;
      openDetailId = null;
      return;
    }
    openDetailId = String(msgId);
    detailPanel.hidden = false;
    detailPanel.innerHTML = '<p class="empty">Loading message detail…</p>';
    try {
      var res = await fetch("/api/message-intel/detail/" + encodeURIComponent(msgId));
      if (!res.ok) throw new Error("HTTP " + res.status);
      var payload = await res.json();
      if (payload.status !== "success") throw new Error(payload.error || "detail failed");
      renderDetailPanel(payload.detail, payload.message);
    } catch (e) {
      detailPanel.innerHTML = '<p class="empty">Could not load message detail.</p>';
    }
  }

  function bindFeedClicks() {
    feed.querySelectorAll("[data-msg-id]").forEach(function (row) {
      row.addEventListener("click", function (ev) {
        var topicBtn = ev.target.closest(".message-intel__topic-chip");
        if (topicBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          var topic = topicBtn.getAttribute("data-topic");
          filters.topic = topic || null;
          saveFilters();
          syncFilterChipStates();
          hydrate();
          return;
        }
        if (ev.target.closest("a")) return;
        toggleMessageDetail(row.getAttribute("data-msg-id"));
      });
    });
  }

  function snippet(text, n) {
    var t = String(text || "").trim();
    if (t.length <= n) return t;
    return t.slice(0, n) + "…";
  }

  function sentimentLabel(analysis, verdict) {
    var s = String((verdict && verdict.verdict) || (analysis && analysis.sentiment) || "").toLowerCase();
    if (s === "bullish" || s === "positive" || s === "buy" || s === "long") return "bullish";
    if (s === "bearish" || s === "negative" || s === "sell" || s === "short") return "bearish";
    return "neutral";
  }

  function sentimentBadgeClass(tag) {
    var t = String(tag || "").toLowerCase();
    if (t === "bullish") return "badge-buy";
    if (t === "bearish") return "badge-sell";
    return "badge-watch";
  }

  function rankClass(rank) {
    if (rank === 1) return "message-intel__rank--gold";
    if (rank === 2) return "message-intel__rank--silver";
    if (rank === 3) return "message-intel__rank--bronze";
    return "";
  }

  function sparklineSvg(points) {
    if (!points || !points.length) return "";
    var w = 56;
    var h = 18;
    var max = Math.max.apply(null, points.concat([1]));
    var step = w / Math.max(1, points.length - 1);
    var coords = points
      .map(function (v, i) {
        var x = (i * step).toFixed(1);
        var y = (h - (v / max) * (h - 2) - 1).toFixed(1);
        return x + "," + y;
      })
      .join(" ");
    return (
      '<svg class="message-intel__spark" width="' +
      w +
      '" height="' +
      h +
      '" viewBox="0 0 ' +
      w +
      " " +
      h +
      '" aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="' +
      coords +
      '"/></svg>'
    );
  }

  function changeLabel(delta) {
    var n = Number(delta) || 0;
    if (n > 0) return '<span class="message-intel__delta message-intel__delta--up">+' + n + " 1h</span>";
    if (n < 0) return '<span class="message-intel__delta message-intel__delta--down">' + n + " 1h</span>";
    return '<span class="message-intel__delta">flat 1h</span>';
  }

  function listenerIdle(listener) {
    listener = listener || {};
    if (listener.live) return false;
    if (listener.desk_ready) return false;
    var reason = String(listener.reason || "");
    return (
      reason === "idle_not_started" ||
      reason === "missing_session" ||
      reason === "disabled" ||
      reason === "missing_telegram_creds"
    );
  }

  function deskLooksReady(listener, payload) {
    listener = listener || {};
    payload = payload || {};
    if (listener.live) return true;
    var meta = payload.meta || {};
    var proof = meta.telegram_proof || {};
    var total = meta.total_messages || 0;
    if (proof.ready && (proof.graded || 0) > 0) return true;
    if (total > 5) return true;
    return false;
  }

  function parseEntities(analysis) {
    if (!analysis) return [];
    var raw = analysis.entities_json;
    var entities = analysis.entities;
    try {
      if (typeof raw === "string") entities = JSON.parse(raw);
      else if (raw && typeof raw === "object") entities = raw;
    } catch (e) {
      entities = entities || {};
    }
    var out = [];
    var seen = {};
    ((entities && entities.subnets) || []).forEach(function (token) {
      var n = Number(token);
      if (!isNaN(n) && !seen[n]) {
        seen[n] = true;
        out.push(n);
      }
    });
    return out;
  }

  function fmtTime(iso) {
    if (!iso) return "";
    var t = Date.parse(iso);
    if (isNaN(t)) return String(iso).slice(0, 16);
    var mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    return Math.floor(hrs / 24) + "d ago";
  }

  function initialLetter(name) {
    var t = String(name || "").trim();
    return t ? t.charAt(0).toUpperCase() : "?";
  }

  function sentimentTagClass(tag) {
    var t = String(tag || "").toLowerCase();
    if (t === "bullish") return "message-intel__tag--bull";
    if (t === "bearish") return "message-intel__tag--bear";
    return "message-intel__tag--neu";
  }

  function signalChips(analysis, verdict) {
    var chips = [];
    var reasoning = verdict && verdict.reasoning ? String(verdict.reasoning).trim() : "";
    if (reasoning && reasoning !== "Adversarial jury verdict from signal vs outcome.") {
      chips.push(reasoning);
    }
    try {
      var raw = analysis && analysis.entities_json;
      var entities = typeof raw === "string" ? JSON.parse(raw) : raw || {};
      (entities.protocols || []).slice(0, 2).forEach(function (p) {
        if (p) chips.push(String(p));
      });
    } catch (e) {
      /* ignore */
    }
    if (verdict && verdict.predicted_timeframe) {
      chips.push(verdict.predicted_timeframe + " lens");
    }
    return chips.slice(0, 3);
  }

  function renderYesterdayLeader(row) {
    if (!yesterdayCard) return;
    if (!row || row.netuid == null) {
      yesterdayCard.hidden = true;
      return;
    }
    yesterdayCard.hidden = false;
    var name = row.name || "SN" + row.netuid;
    if (yesterdayIcon) yesterdayIcon.textContent = initialLetter(name);
    if (yesterdayLink) {
      yesterdayLink.href = "/subnet/" + encodeURIComponent(String(row.netuid));
      yesterdayLink.innerHTML =
        esc(name) + ' <span class="message-intel__hero-sn">· SN' + esc(row.netuid) + "</span>";
    }
    if (yesterdayStats) {
      var sent = row.sentiment || "Cautious";
      var sentClass =
        sent.toLowerCase() === "bullish"
          ? "message-intel__sent--bull"
          : sent.toLowerCase() === "bearish"
            ? "message-intel__sent--bear"
            : "";
      yesterdayStats.innerHTML =
        esc(row.mentions) +
        " mentions · <span class=\"" +
        sentClass +
        '">' +
        esc(sent) +
        "</span>" +
        (row.date ? " · " + esc(row.date) : "");
    }
    if (yesterdayChips) {
      var chips = row.why_chips || [];
      if (chips.length) {
        yesterdayChips.hidden = false;
        yesterdayChips.innerHTML = chips
          .map(function (c, i) {
            return (
              '<span class="message-intel__chip' +
              (i === 0 ? " message-intel__chip--hot" : "") +
              '">' +
              esc(c) +
              "</span>"
            );
          })
          .join("");
      } else {
        yesterdayChips.hidden = true;
        yesterdayChips.innerHTML = "";
      }
    }
    if (yesterdayRunner) {
      var ru = row.runner_up;
      if (ru && ru.netuid != null) {
        yesterdayRunner.hidden = false;
        yesterdayRunner.innerHTML =
          "Runner-up: <b>" + esc(ru.name || "SN" + ru.netuid) + " SN" + esc(ru.netuid) + "</b> · " + esc(ru.mentions || 0) + " mentions";
      } else {
        yesterdayRunner.hidden = true;
        yesterdayRunner.innerHTML = "";
      }
    }
  }

  function renderTrending(rows, listener, windowLabel) {
    if (listenerIdle(listener) && (!rows || !rows.length)) {
      return (
        '<p class="empty">Quiet — Telegram ingest is warming up. Trending fills as Subnet Summers messages land.</p>'
      );
    }
    if (!rows || !rows.length) {
      return '<p class="empty">No subnet chatter in the last day. Check back after the group warms up.</p>';
    }
    var html = '<div class="message-intel__trend-rows">';
    rows.slice(0, 6).forEach(function (row, idx) {
      var rank = idx + 1;
      var tag = String(row.sentiment || "Cautious");
      html +=
        '<div class="message-intel__trend-row">' +
        '<span class="message-intel__rank ' +
        rankClass(rank) +
        '">' +
        (rank < 10 ? "0" : "") +
        rank +
        "</span>" +
        '<span class="message-intel__t-icon" aria-hidden="true">' +
        esc(initialLetter(row.name)) +
        "</span>" +
        '<div class="message-intel__t-body">' +
        '<a class="message-intel__t-name" href="/subnet/' +
        esc(row.netuid) +
        '">' +
        esc(row.name) +
        '<span class="message-intel__t-sn">SN' +
        esc(row.netuid) +
        "</span></a>" +
        '<div class="message-intel__t-count">' +
        esc(row.mentions) +
        " mentions</div></div>" +
        '<div class="message-intel__t-right">' +
        sparklineSvg(row.sparkline) +
        '<span class="message-intel__tag ' +
        sentimentTagClass(tag) +
        '">' +
        esc(tag.toUpperCase()) +
        "</span></div></div>";
    });
    html += "</div>";
    return html;
  }

  function renderTrendingV2(rows, windowLabel, meta) {
    if (!trendingEl) return;
    if (!rows || !rows.length) {
      var archiveCount = meta && meta.total_messages != null ? Number(meta.total_messages) : 0;
      var dayCount =
        meta && meta.summary_24h && meta.summary_24h.message_count != null
          ? Number(meta.summary_24h.message_count)
          : 0;
      var archiveLabel = archiveCount
        ? archiveCount + ' archived message' + (archiveCount === 1 ? '' : 's')
        : 'The archive is ready';
      var dayLabel = dayCount
        ? dayCount + ' message' + (dayCount === 1 ? '' : 's') + ' in the 24h window'
        : 'No 24h messages have landed yet';
      trendingEl.innerHTML =
        '<div class="message-intel__trend-status" role="status">' +
        '<strong>Ranked chatter is quiet right now.</strong>' +
        '<span>' + esc(archiveLabel) + ' · ' + esc(dayLabel) + '.</span>' +
        '<small>New subnet mentions will appear here as the archive warms.</small>' +
        '</div>';
      return;
    }
    if (trendingTitle) trendingTitle.textContent = "Currently trending";
    if (trendingUnit) trendingUnit.textContent = windowLabel || "1h";
    trendingEl.innerHTML =
      '<div class="message-intel__trend-rows">' +
       rows.slice(0, 6).map(function (row, idx) {
        var score = row.chatter_power != null ? Number(row.chatter_power) : Number(row.heat) || 0;
        var delta = row.delta != null ? Number(row.delta) : 0;
        return '<div class="message-intel__trend-row">' +
          '<span class="message-intel__rank">' + esc((idx + 1 < 10 ? "0" : "") + (idx + 1)) + '</span>' +
          '<span class="message-intel__t-icon" aria-hidden="true">' + esc(initialLetter(row.name)) + '</span>' +
          '<div class="message-intel__t-body">' +
          '<a class="message-intel__t-name" href="/subnet/' + esc(row.netuid) + '">' + esc(row.name) + '<span class="message-intel__t-sn">SN' + esc(row.netuid) + '</span></a>' +
          '<div class="message-intel__t-count">' + esc(row.mentions || 0) + ' mentions · ' + esc(score.toFixed(3)) + '</div>' +
          (row.why ? '<div class="message-intel__trend-why">' + esc(row.why) + '</div>' : '') +
          '</div>' +
          '<div class="message-intel__t-right">' +
          '<span class="message-intel__tag message-intel__tag--' + esc(String(row.sentiment || "cautious").toLowerCase()) + '">' + esc(String(row.sentiment || "cautious").toUpperCase()) + '</span>' +
           '<div class="message-intel__trend-delta">' + esc((delta > 0 ? "+" : "") + delta.toFixed(3)) + '</div>' +
           watchlistToggleButton(row.netuid) +
          '</div></div>';
      }).join("") +
      '</div>';
  }

  function renderWatchlistPanel(trending) {
    var root = document.getElementById("message-intel-watchlist-panel");
    if (!root) return;
    if (watchlistState.upgrade) {
      root.innerHTML = '<div class="message-intel__upgrade"><b>Upgrade to PRO</b><p>My Desk watchlists and alert thresholds are part of PRO.</p></div>';
      return;
    }
    if (watchlistState.loading) {
      root.innerHTML = '<p class="empty">Loading your watchlist…</p>';
      return;
    }
    var rows = (trending || []).filter(function (row) { return isWatchlisted(row.netuid); });
    if (!rows.length) {
      root.innerHTML = '<p class="empty">No pinned subnets yet. Add one from trending cards or subnet rows.</p>';
      return;
    }
    var link = '<div class="message-intel__watch-link"><button type="button" class="message-intel__watch-toggle" data-watch-link>Link Telegram bot</button><span id="message-intel-watch-link-code"></span></div>';
    root.innerHTML = link + (rows.length ? rows.map(function (row) {
      return '<div class="message-intel__watch-row" data-netuid="' + esc(row.netuid) + '">' +
        '<a href="/subnet/' + esc(row.netuid) + '"><b>' + esc(row.name || "SN" + row.netuid) + '</b> <span>SN' + esc(row.netuid) + '</span></a>' +
        '<label class="message-intel__watch-meta">Alert ≥ ' +
        '<input class="message-intel__watch-threshold" type="number" min="0" max="100" step="1" data-watch-threshold="' + esc(row.netuid) + '" value="' + esc(watchlistThreshold(row.netuid) != null ? watchlistThreshold(row.netuid) : 60) + '" aria-label="Alert threshold for SN' + esc(row.netuid) + '">%</label>' +
        watchlistToggleButton(row.netuid) +
        '</div>';
    }).join("") : '<p class="empty">No pinned subnets yet. Add one from trending cards or subnet rows.</p>');
    bindWatchlistInteractions();
  }

  function renderMyPulse(trending) {
    var root = document.getElementById("message-intel-my-pulse");
    if (!root) return;
    if (watchlistState.upgrade) {
      root.innerHTML = '<div class="message-intel__upgrade"><b>Upgrade to PRO</b><p>My Pulse is available with My Desk.</p></div>';
      return;
    }
    var rows = (trending || []).filter(function (row) { return isWatchlisted(row.netuid); });
    if (!rows.length) {
      root.innerHTML = '<p class="empty">Pin a subnet to see its ChatterPower pulse here.</p>';
      return;
    }
    root.innerHTML = rows.map(function (row) {
      var power = Number(row.chatter_power != null ? row.chatter_power : row.heat) || 0;
      var delta = Number(row.delta) || 0;
      return '<div class="message-intel__pulse-row"><a href="/subnet/' + esc(row.netuid) + '"><b>' + esc(row.name || "SN" + row.netuid) + '</b></a>' +
        '<span>Power ' + esc(power.toFixed(3)) + '</span><span class="message-intel__trend-delta">' + esc((delta > 0 ? "+" : "") + delta.toFixed(3)) + '</span></div>';
    }).join("");
    bindWatchlistInteractions();
  }

  function renderChampions(rows, authorsUnavailable) {
    if (authorsUnavailable) {
      return '<p class="empty">Weekly champions API unavailable — redeploy to pick up the latest build.</p>';
    }
    if (!rows || !rows.length) {
      return '<p class="empty">No contributor history yet — champions appear as Subnet Summers traffic grades.</p>';
    }
    var maxInf = Math.max.apply(
      null,
      rows.map(function (r) {
        return Number(r.influence_score) || 0;
      }).concat([1])
    );
    var html = '<div class="message-intel__champ-rows">';
    rows.slice(0, 6).forEach(function (row, idx) {
      var rank = idx + 1;
      var handle = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : row.author_name;
      var inf = Number(row.influence_score) || 0;
      var pct = Math.round((inf / maxInf) * 100);
      var basis =
        row.hit_rate != null && row.graded
          ? esc(row.hit_rate) + "% hit-rate · " + esc(row.message_count) + " calls"
          : esc(row.message_count) + " msgs · " + esc(row.subnet_count) + " subnets";
      html +=
        '<div class="message-intel__champ-row">' +
        '<span class="message-intel__rank ' +
        rankClass(rank) +
        '">' +
        (rank < 10 ? "0" : "") +
        rank +
        "</span>" +
        '<span class="message-intel__champ-avatar" aria-hidden="true">' +
        esc(row.initials || initialLetter(row.author_name)) +
        "</span>" +
        '<div class="message-intel__champ-body">' +
        '<div class="message-intel__champ-name">' +
        esc(handle || "Unknown") +
        "</div>" +
        '<div class="message-intel__champ-basis">' +
        basis +
        "</div></div>" +
        '<div class="message-intel__champ-score">' +
        '<div class="message-intel__champ-num">' +
        esc(inf.toFixed ? inf.toFixed(1) : inf) +
        "</div>" +
        '<div class="message-intel__champ-bar"><div class="message-intel__champ-bar-fill" style="width:' +
        pct +
        '%"></div></div></div></div>';
    });
    html += "</div>";
    return html;
  }

  function renderReactionCrowns(rows) {
    if (!rows || !rows.length) {
      return '<p class="empty">No reaction crowns yet — they appear as the group reacts.</p>';
    }
    var html = '<div class="message-intel__crown-rows">';
    rows.forEach(function (row) {
      var handle =
        row.display_name ||
        (row.author_username
          ? "@" + String(row.author_username).replace(/^@/, "")
          : row.author_name) ||
        "Unknown";
      html +=
        '<div class="message-intel__crown-row">' +
        '<span class="message-intel__crown-emoji" aria-hidden="true">' +
        esc(row.emoji || "") +
        "</span>" +
        '<div class="message-intel__crown-body">' +
        '<div class="message-intel__crown-label">' +
        esc(row.label || row.key || "") +
        "</div>" +
        '<div class="message-intel__crown-name">' +
        esc(handle) +
        "</div></div>" +
        '<div class="message-intel__crown-count">' +
        esc(row.count) +
        "</div></div>";
    });
    html += "</div>";
    return html;
  }

  function formatCompactCount(n) {
    var v = Number(n) || 0;
    if (v >= 1000) return (v / 1000).toFixed(v >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k";
    return String(v);
  }

  function renderWeekTopComment(row) {
    if (!weekTopEl) return;
    if (!row || !row.content) {
      weekTopEl.hidden = true;
      return;
    }
    var whyEl = document.getElementById("message-intel-week-top-why");
    var quoteEl = document.getElementById("message-intel-week-top-quote");
    var authorEl = document.getElementById("message-intel-week-top-author");
    var statsEl = document.getElementById("message-intel-week-top-stats");
    var handle =
      row.display_name ||
      (row.author_username
        ? "@" + String(row.author_username).replace(/^@/, "")
        : row.author_name) ||
      "Unknown";
    if (whyEl) whyEl.textContent = row.why || "Most engaged";
    if (quoteEl) quoteEl.textContent = "“" + String(row.content) + "”";
    if (authorEl) authorEl.textContent = handle;
    if (statsEl) {
      var parts = [];
      var views = Number(row.views) || 0;
      var replies = Number(row.replies) || 0;
      var reacts = Number(row.reaction_total) || 0;
      var forwards = Number(row.forwards) || 0;
      var topRx = row.top_reaction || null;
      var dominant = String(row.why || "");
      if (reacts > 0) {
        var rxLabel = topRx && topRx.emoji ? topRx.emoji + " " + formatCompactCount(reacts) : formatCompactCount(reacts) + " reacts";
        parts.push({ label: rxLabel, hot: dominant.indexOf("reacted") !== -1 });
      }
      if (views > 0) {
        parts.push({ label: formatCompactCount(views) + " views", hot: dominant.indexOf("viewed") !== -1 });
      }
      if (replies > 0) {
        parts.push({ label: formatCompactCount(replies) + " replies", hot: dominant.indexOf("replied") !== -1 });
      }
      if (forwards > 0) {
        parts.push({ label: formatCompactCount(forwards) + " forwards", hot: dominant.indexOf("forwarded") !== -1 });
      }
      statsEl.innerHTML = parts
        .map(function (p) {
          return (
            '<span class="message-intel__week-top-stat' +
            (p.hot ? " message-intel__week-top-stat--hot" : "") +
            '">' +
            esc(p.label) +
            "</span>"
          );
        })
        .join("");
    }
    weekTopEl.hidden = false;
  }

  function renderSubnetChips(netuids) {
    if (!netuids || !netuids.length) return "";
    return (
      '<div class="message-intel__chips">' +
      netuids
        .slice(0, 4)
        .map(function (n) {
          return (
            '<a class="message-intel__chip" href="/subnet/' +
            esc(n) +
            '">SN' +
            esc(n) +
            "</a>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function renderTopicChips(topics) {
    if (!topics || !topics.length) return "";
    return (
      '<div class="message-intel__topic-chips">' +
      topics
        .slice(0, 4)
        .map(function (t) {
          return (
            '<button type="button" class="message-intel__topic-chip" data-topic="' +
            esc(t) +
            '">' +
            esc(t) +
            "</button>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function renderMessages(rows) {
    if (!rows || !rows.length) return "";
    var html = '<div class="message-intel__feed-rows">';
    rows.forEach(function (row, i) {
      var verdict = row.verdict || {};
      var analysis = row.analysis || {};
      var label = sentimentLabel(analysis, verdict);
      var railClass =
        label === "bullish" ? "is-bull" : label === "bearish" ? "is-bear" : "is-neu";
      var conv = verdict.conviction != null ? Math.round(Number(verdict.conviction)) : null;
      var direction = String(verdict.predicted_direction || "").toLowerCase();
      var dirArrow =
        direction === "up" || direction === "long" || direction === "buy"
          ? " ↑"
          : direction === "down" || direction === "short" || direction === "sell"
            ? " ↓"
            : "";
      var author = row.author_username
        ? "@" + String(row.author_username).replace(/^@/, "")
        : row.author_name || "unknown";
      var netuids = parseEntities(analysis);
      var why = signalChips(analysis, verdict);
      var hotClass = conv != null && conv >= 60 ? " message-intel__feed-row--hot" : "";
      html +=
        '<article class="message-intel__feed-row message-intel__feed-row--clickable message-intel__feed-row--enter' +
        hotClass +
        " " +
        railClass +
        '" style="--mi-i: ' +
        i +
        '" data-msg-id="' +
        esc(row.id) +
        '" tabindex="0" role="button">' +
        '<div class="message-intel__rail-node" aria-hidden="true"></div>' +
        '<div class="message-intel__feed-body">' +
        '<div class="message-intel__feed-top">' +
        '<span class="message-intel__f-avatar" aria-hidden="true">' +
        esc(initialLetter(author)) +
        "</span>" +
        '<span class="message-intel__f-handle">' +
        esc(author) +
        "</span>" +
        '<span class="message-intel__f-tag ' +
        sentimentTagClass(label) +
        '">' +
        esc(label.toUpperCase()) +
        "</span>" +
        (conv != null
          ? '<span class="message-intel__f-conv' +
            (conv >= 60 ? " message-intel__f-conv--high" : "") +
            '">' +
            esc(conv) +
            "% conv" +
            dirArrow +
            "</span>"
          : "") +
        '<span class="message-intel__f-time">' +
        esc(fmtTime(row.timestamp)) +
        "</span></div>" +
        '<p class="message-intel__f-text">' +
        esc(snippet(row.content, 280));
      if (netuids.length) {
        html += '<span class="message-intel__sn-inline">SN' + esc(netuids[0]) + '</span>';
        html += watchlistToggleButton(netuids[0]);
      }
      html += "</p>";
      html += proofPill(row.proof);
      if (why.length) {
        html +=
          '<div class="message-intel__signal-strip"><span class="message-intel__why-label">WHY</span>' +
          why
            .map(function (c, i) {
              var hitClass = "";
              if (i === 0) {
                hitClass =
                  label === "bearish"
                    ? " message-intel__sig-chip--hit-orange"
                    : label === "bullish"
                      ? " message-intel__sig-chip--hit-blue"
                      : " message-intel__sig-chip--hit-blue";
              }
              return (
                '<span class="message-intel__sig-chip' +
                hitClass +
                '">' +
                esc(c) +
                "</span>"
              );
            })
            .join("") +
          "</div>";
      }
      var topics = row.topics || [];
      if (topics.length) {
        html += renderTopicChips(topics);
      }
      html += "</div></article>";
    });
    html += "</div>";
    return html;
  }

  function renderFeedEmpty(listener) {
    listener = listener || {};
    if (listener.live) {
      return (
        '<p class="empty">Listening to Subnet Summers — messages appear here as the group talks.</p>'
      );
    }
    if (listener.reason === "disabled") {
      return '<p class="empty">Telegram listener is off on this deploy (<code>MESSAGE_INTEL_LISTENER</code>).</p>';
    }
    if (listener.reason === "missing_session") {
      return (
        '<p class="empty">Telegram creds are set — paste <code>TELEGRAM_SESSION_STRING</code> (see <code>DEPLOY.md</code>), then set <code>MESSAGE_INTEL_LISTENER=auto</code>.</p>'
      );
    }
    if (listener.reason === "telethon_unavailable") {
      return '<p class="empty">Telethon missing in runtime image — ingest via API only.</p>';
    }
    if (listener.reason === "missing_telegram_creds") {
      return '<p class="empty">Telegram creds not configured — ingest via API only.</p>';
    }
    if (listener.reason === "idle_not_started") {
      return '<p class="empty">Listener configured — warming up (~2 min after boot).</p>';
    }
    if (listener.reason === "listener_stopped") {
      return '<p class="empty">Listener restarting — archived messages stay visible; live feed resumes shortly.</p>';
    }
    return '<p class="empty">No Telegram messages ingested yet.</p>';
  }

  function isOpsHint(text) {
    if (!text) return false;
    return /TELEGRAM_|MESSAGE_INTEL_|DEPLOY\.md|fly logs|bootstrap_telegram/i.test(String(text));
  }

  function humanModeLabel(mode) {
    if (mode === "live") return "Live";
    if (mode === "reconnecting") return "Reconnecting";
    if (mode === "archive") return "Archive";
    return "Warming up";
  }

  function applyMeta(payload, status) {
    var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
    var total =
      (status && status.store && status.store.total_messages) ||
      (payload.meta && payload.meta.total_messages) ||
      0;
    var highConv =
      (status && status.store && status.store.high_conviction_count) ||
      (payload.meta && payload.meta.high_conviction_count) ||
      0;
    var group = listener.group_title || listener.monitored_group || "OfficialSubnetSummer";
    var deskReady = deskLooksReady(listener, payload);
    var mode =
      listener.display_mode ||
      (listener.live && !listener.feed_stale ? "live" : deskReady ? "archive" : "warming");

    if (groupLink) {
      groupLink.href = GROUP_URL;
      groupLink.textContent = "Subnet Summers";
    }

    if (meta) {
      var parts = ["<b>" + esc(group) + "</b>", humanModeLabel(mode)];
      parts.push(esc(total) + " messages");
      if (highConv) parts.push(esc(highConv) + " high conviction");
      if (mode === "archive" && listener.feed_stale) {
        parts.push("feed quiet — backfill on");
      }
      meta.innerHTML = parts.join(" · ");
      var tooltip = listener.ops_hint || listener.hint || "";
      if (tooltip && isOpsHint(tooltip)) {
        meta.title = tooltip;
      } else if (listener.feed_stale && listener.last_message_at) {
        meta.title = "Last message " + listener.last_message_at + " — polling Telegram history";
      } else if (tooltip && mode === "warming") {
        meta.title = tooltip;
      } else {
        meta.removeAttribute("title");
      }
    }

    if (liveTag) {
      if (mode === "live") {
        liveTag.textContent = "Live";
        liveTag.hidden = false;
      } else if (mode === "reconnecting") {
        liveTag.textContent = "Reconnecting";
        liveTag.hidden = false;
      } else if (mode === "archive") {
        liveTag.textContent = "Archive";
        liveTag.hidden = false;
      } else {
        liveTag.hidden = true;
      }
    }
    if (pulse) pulse.hidden = mode !== "live";

    if (sub) {
      if (mode === "live") {
        sub.innerHTML =
          'Live read of <a class="message-intel__group-link" href="' +
          GROUP_URL +
          '" target="_blank" rel="noopener noreferrer">Subnet Summers</a> — trending names, top contributors, and jury-scored messages.';
      } else if (mode === "archive") {
        sub.textContent = listener.feed_stale
          ? "Subnet Summers archive — backfill polling Telegram history."
          : "Subnet Summers desk loaded from archive — listener runs on the worker machine.";
      } else if (mode === "reconnecting") {
        sub.textContent = "Reconnecting to Subnet Summers — graded messages will appear here.";
      } else {
        sub.textContent = "Connecting to Subnet Summers — graded messages will appear here.";
      }
    }

    if (feedHint && (listener.live || deskReady)) {
      feedHint.textContent = "Newest first · jury conviction · updates ~60s";
    }

    lastStatus = status;
  }

  async function fetchJsonWithRetry(url, attempts) {
    var tries = attempts || 3;
    var lastErr = null;
    for (var i = 0; i < tries; i++) {
      try {
        var opts = {};
        if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
          opts.signal = AbortSignal.timeout(18000);
        }
        var res = await fetch(url, opts);
        if (res.ok) return await res.json();
        if (res.status === 503 && i < tries - 1) {
          await new Promise(function (r) {
            setTimeout(r, 600 * (i + 1));
          });
          continue;
        }
        throw new Error("HTTP " + res.status);
      } catch (err) {
        lastErr = err;
        if (i < tries - 1) {
          await new Promise(function (r) {
            setTimeout(r, 600 * (i + 1));
          });
        }
      }
    }
    throw lastErr || new Error("fetch failed");
  }

  function finishFeedHydrate() {
    if (feed) feed.setAttribute("aria-busy", "false");
  }

  async function hydrate() {
    try {
      var status = null;
      var payload = null;
      try {
        status = await fetchJsonWithRetry("/api/message-intel/status");
      } catch (statusErr) {
        status = null;
      }
      try {
        payload = await fetchJsonWithRetry(buildListUrl(24));
      } catch (listErr) {
        payload = null;
      }
      if (!payload) {
        if (status && status.listener && (status.listener.live || status.store)) {
          applyMeta({ messages: [], meta: { total_messages: 0 }, empty: true }, status);
          if (meta) meta.textContent = "reconnecting";
          if (feed) {
            feed.innerHTML = window.buildDeskEmptyState
              ? window.buildDeskEmptyState({
                  kind: 'warming',
                  title: 'Telegram desk reconnecting',
                  body: 'Feed will retry shortly.',
                  classExtra: 'desk-empty-state--inline',
                })
              : '<p class="desk-empty desk-empty--warming">Desk warming — feed will retry shortly.</p>';
          }
          finishFeedHydrate();
          return;
        }
        throw new Error("message-intel unavailable");
      }

      applyMeta(payload, status);

      var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
      var trending = (payload.meta && payload.meta.trending) || [];
      try {
        var trendingV2 = await fetchJsonWithRetry("/api/message-intel/trending-v2?limit=12&rank_hours=1&window_hours=24");
        if (trendingV2 && Array.isArray(trendingV2.items) && trendingV2.items.length) {
          trending = trendingV2.items;
        } else if (!trending.length) {
          // A quiet one-hour rank should not hide a populated 24-hour desk.
          var archiveTrending = await fetchJsonWithRetry(
            "/api/message-intel/trending-v2?limit=12&rank_hours=24&window_hours=24"
          );
          if (archiveTrending && Array.isArray(archiveTrending.items) && archiveTrending.items.length) {
            trending = archiveTrending.items;
          }
        }
      } catch (trendingErr) {
        /* Keep the server-rendered compatibility rollup. */
      }
      var trendingWindow = (payload.meta && payload.meta.trending_window) || "1h";
       latestTrendingRows = trending;
      var trendingUnit = document.querySelector("#message-intel-trending-card .message-intel__panel-unit");
      if (trendingUnit) trendingUnit.textContent = trendingWindow;
      renderYesterdayLeader((payload.meta && payload.meta.yesterday_leader) || null);
      renderWeekTopComment((payload.meta && payload.meta.week_top_comment) || null);
      renderSummary24h((payload.meta && payload.meta.summary_24h) || null);
      renderTelegramProof((payload.meta && payload.meta.telegram_proof) || null);
      hydrateCallerLeaderboard();
      hydrateConsensus();
      hydrateDivergence();
      var chatter = (payload.meta && payload.meta.high_conviction_strip) || [];
      if (!chatter.length) {
        try {
          var chatterPayload = await fetchJsonWithRetry("/api/message-intel/chatter?min_conviction=60&limit=5");
          chatter = (chatterPayload && chatterPayload.messages) || [];
        } catch (chatterErr) {
          /* Keep the honest empty state when chatter is unavailable. */
        }
      }
      renderHighConvictionStrip(chatter);
      renderSubnetFilterChips(trending);
      renderWatchlistPanel(trending);
       renderMyPulse(trending);
      syncFilterChipStates();
       renderTrendingV2(trending, trendingWindow, payload.meta || {});
       bindWatchlistInteractions();

      var authorsUnavailable = false;
      var authors = [];
      var crowns = (payload.meta && payload.meta.reaction_crowns) || [];
      try {
        var authorsPayload = await fetchJsonWithRetry("/api/message-intel/authors?days=7&limit=8");
        authors = authorsPayload.authors || [];
        if (authorsPayload.reaction_crowns && authorsPayload.reaction_crowns.length) {
          crowns = authorsPayload.reaction_crowns;
        }
      } catch (e) {
        authorsUnavailable = true;
      }
      if (championsEl) {
        championsEl.innerHTML = renderChampions(authors, authorsUnavailable);
      }
      if (crownsEl) {
        crownsEl.innerHTML = renderReactionCrowns(crowns);
      }

      if (payload.filtered_empty) {
        feed.innerHTML = renderFilterEmpty();
      } else if (payload.empty) {
        feed.innerHTML = renderFeedEmpty(status && status.listener);
      } else {
        feed.innerHTML = renderMessages(payload.messages);
        bindFeedClicks();
      }
      finishFeedHydrate();
    } catch (e) {
      if (meta) meta.textContent = "unavailable";
      if (pulse) pulse.hidden = true;
      if (trendingEl) {
        trendingEl.innerHTML = '<p class="desk-empty desk-empty--error">Trending temporarily unavailable.</p>';
      }
      if (championsEl) {
        championsEl.innerHTML = '<p class="desk-empty desk-empty--error">Champions temporarily unavailable.</p>';
      }
      if (crownsEl) {
        crownsEl.innerHTML = '<p class="desk-empty desk-empty--error">Reaction crowns temporarily unavailable.</p>';
      }
      if (weekTopEl) weekTopEl.hidden = true;
      feed.innerHTML =
        '<p class="desk-empty desk-empty--error">Telegram desk unreachable — will retry shortly.</p>';
      finishFeedHydrate();
    }
  }

  document.addEventListener("home:cockpit-tick", hydrate);
  if (refreshBtn) {
    refreshBtn.addEventListener("click", hydrate);
  }
  if (callersEl) {
    callersEl.querySelectorAll("[data-caller-days]").forEach(function (button) {
      button.addEventListener("click", function () {
        callerDays = Number(button.getAttribute("data-caller-days")) || 30;
        callersEl.querySelectorAll("[data-caller-days]").forEach(function (tab) { tab.classList.toggle("is-active", tab === button); });
        hydrateCallerLeaderboard();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindPulseModes();
      bindFilterClicks();
      syncFilterChipStates();
       hydrateWatchlist();
      hydrate();
      refreshTimer = window.setInterval(hydrate, 60000);
    });
  } else {
    bindPulseModes();
    bindFilterClicks();
    syncFilterChipStates();
    hydrateWatchlist();
    hydrate();
    refreshTimer = window.setInterval(hydrate, 60000);
  }

  window.addEventListener("pagehide", function () {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
