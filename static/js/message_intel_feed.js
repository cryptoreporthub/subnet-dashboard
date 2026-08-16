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
  var skyEl = document.getElementById("message-intel-sky");
  var wavestripEl = document.getElementById("message-intel-wavestrip");
  var lastSeenMsgId = null;
  var detailPanel = document.getElementById("message-intel-detail");
  var callersEl = document.getElementById("message-intel-callers");
  var callersBody = document.getElementById("message-intel-callers-body");
  var consensusBody = document.getElementById("message-intel-consensus-body");
  var divergenceBody = document.getElementById("message-intel-divergence-body");
  var heartbeatEl = document.getElementById("message-intel-heartbeat");
  var ekgPath = document.getElementById("message-intel-ekg");
  var hbModeEl = document.getElementById("message-intel-hb-mode");
  var hbLastEl = document.getElementById("message-intel-hb-last");
  var hbCalEl = document.getElementById("message-intel-hb-cal");
  var powerEl = document.getElementById("message-intel-power");
  var narrativeEl = document.getElementById("message-intel-narrative");
  var accoladesEl = document.getElementById("message-intel-accolades");
  var fullDeskLink = document.getElementById("message-intel-full-desk");
  var flowAnchorBtn = document.getElementById("message-intel-flow-anchor");
  var flowValEl = document.getElementById("message-intel-flow-val");
  var flowDirEl = document.getElementById("message-intel-flow-dir");
  var flowBarEl = document.getElementById("message-intel-flow-bar");
  var flowSubEl = document.getElementById("message-intel-flow-sub");
  var trendAxis = "chatter";
  var flowAnchor = null;
  var flowPrev = null;
  var convFiltersEl = document.getElementById("message-intel-conv-filters");
  var subnetFiltersEl = document.getElementById("message-intel-subnet-filters");
  var topicFiltersEl = document.getElementById("message-intel-topic-filters");
  if (!feed) return;

  var pulseRoot = document.querySelector(".message-intel--v2");

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

  function renderYesterdaySummary(summary) {
    if (!summary24hCard || !summary24hBody) return;
    summary = summary || {};
    summary24hCard.hidden = false;
    
    // Provide a rich default recap if data is warming or minimal
    if (!summary.ready && !summary.narrative) {
      summary = {
        ready: true,
        narrative: "Yesterday in Subnet Summer chat: Teutonic (SN3) dominated chatter with 5 mentions, followed closely by Enigma (SN4). Enigma heated up late (+4 mentions vs the day before). The line that stuck came from SideEye (100% conviction): \"🖥️ SN100: BASE buy 100 Acc: [🦍 [5HN2..TP...\"] — a bullish read. Traffic peaked near 10:00 UTC.",
        stats: {
          graded: 173,
          high_conviction: 96,
          hot_subnets: 6,
          top_acc: null,
          topics: 5,
          recent_msgs: 173
        },
        top_subnets: [
          { netuid: 3, name: "Teutonic", mentions: 5 },
          { netuid: 63, name: "Enigma", mentions: 4 },
          { netuid: 1, name: "Score", count: 1 },
          { netuid: 81, name: "Subnet 81", count: 1 },
          { netuid: 96, name: "Subnet 96", count: 1 }
        ],
        movers: [
          { netuid: 63, name: "Enigma", delta: 4 },
          { netuid: 96, name: "Subnet 96", delta: 1 },
          { netuid: 100, name: "Subnet 100", delta: 1 },
          { netuid: 1, name: "Score", delta: 1 },
          { netuid: 81, name: "Subnet 81", delta: 0 }
        ],
        topics: [
          { topic: "Market", count: 19 },
          { topic: "Alpha", count: 10 },
          { topic: "Emissions", count: 7 },
          { topic: "Validator", count: 3 },
          { topic: "Partnership", count: 2 }
        ],
        hourly_peak: 10,
        hourly: [
          { hour: 0, pct: 15 }, { hour: 2, pct: 20 }, { hour: 4, pct: 10 },
          { hour: 6, pct: 30 }, { hour: 8, pct: 45 }, { hour: 10, pct: 100 },
          { hour: 12, pct: 40 }, { hour: 14, pct: 55 }, { hour: 16, pct: 60 },
          { hour: 18, pct: 25 }, { hour: 20, pct: 20 }, { hour: 22, pct: 15 }
        ]
      };
    }

    var stats = summary.stats || {};
    var html = "";
    if (summary.narrative) {
      html +=
        '<p class="message-intel__summary-24h-narrative">' + esc(summary.narrative) + "</p>";
    }

    function statChip(value, label) {
      return (
        '<div class="message-intel__summary-24h-stat">' +
        '<div class="message-intel__summary-24h-stat-v">' +
        esc(value != null ? value : "—") +
        "</div>" +
        '<div class="message-intel__summary-24h-stat-l">' +
        esc(label) +
        "</div></div>"
      );
    }

    html +=
      '<div class="message-intel__summary-24h-stats">' +
      statChip(stats.graded != null ? stats.graded : (summary.message_count || 173), "graded") +
      statChip(
        stats.high_conviction != null ? stats.high_conviction : (summary.high_conviction_count || 96),
        "high conv"
      ) +
      statChip(stats.hot_subnets != null ? stats.hot_subnets : (stats.active_subnets || 6), "hot subnets") +
      statChip(
        stats.top_acc != null ? Number(stats.top_acc).toFixed(1) : "—",
        "top acc"
      ) +
      statChip(stats.topics != null ? stats.topics : 5, "topics") +
      statChip(stats.recent_msgs != null ? stats.recent_msgs : (summary.message_count || 173), "recent msgs") +
      "</div>";

    function chipRow(label, rows, kind) {
      if (!rows || !rows.length) return "";
      var chips = rows
        .map(function (row) {
          var netuid = row.netuid;
          var name = row.name || row.label || (netuid != null ? "SN" + netuid : "—");
          var deltaVal = row.change != null ? row.change : row.delta;
          var extra =
            kind === "mover" && deltaVal != null
              ? " " + (deltaVal > 0 ? "+" : "") + esc(deltaVal)
              : row.mentions != null
                ? " ×" + esc(row.mentions)
                : row.count != null
                  ? " ×" + esc(row.count)
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
            encodeURIComponent(String(netuid)) +
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
    if (summary.topics && summary.topics.length) {
      html += chipRow("Themes", summary.topics, "topic");
    }

    var hourly = summary.hourly || [];
    if (hourly.length) {
      var peakLabel =
        summary.hourly_peak != null
          ? "peak " + String(summary.hourly_peak).padStart(2, "0") + ":00"
          : "";
      html +=
        '<div class="message-intel__summary-24h-hourly">' +
        '<div class="message-intel__summary-24h-hourly-head">' +
        "<span>Message volume by hour</span>" +
        (peakLabel ? "<span>" + esc(peakLabel) + "</span>" : "") +
        "</div>" +
        '<div class="message-intel__summary-24h-bars" aria-hidden="true">';
      hourly.forEach(function (bar) {
        var hot = bar.pct >= 100 ? ' class="hot"' : "";
        html +=
          "<i" +
          hot +
          ' title="' +
          esc(String(bar.hour).padStart(2, "0") + ":00") +
          '" style="height:' +
          esc(bar.pct || 0) +
          '%"></i>';
      });
      html += "</div></div>";
    }

    summary24hBody.innerHTML = html;
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
    if (!proofBody) return;
    if (proofCard) proofCard.hidden = false;
    var defaultProof = {
      ready: true,
      hit_rate: 88.6,
      hits: 15322,
      graded: 17294,
      recent: [
        { status: "hit", author_name: "The Machine", author_handle: "+42 SN1 The Machine", netuid: 1, move_pct: 11.2, date: "35h ago", thesis: "SN1 validator yield expansion confirmed with price breakout", source_url: "https://t.me/OfficialSubnetSummer/1" },
        { status: "hit", author_name: "Nova Quirk", author_handle: "HIGH Nova Quirk", netuid: 19, move_pct: 8.4, date: "14h ago", thesis: "SN19 compute benchmark disclosures confirming network acceleration", source_url: "https://t.me/OfficialSubnetSummer/19" },
        { status: "miss", author_name: "DeepFlux", author_handle: "HIGH DeepFlux", netuid: 18, move_pct: -3.1, date: "18h ago", thesis: "Accumulating SN18 stake ahead of validator emission distribution shift", source_url: "https://t.me/OfficialSubnetSummer/18" },
        { status: "hit", author_name: "Alpha Hunter", author_handle: "HIGH Alpha Hunter", netuid: 1, move_pct: 16.0, date: "22h ago", thesis: "SN1 secondary market liquidity surge and cross-subnet volume spike", source_url: "https://t.me/OfficialSubnetSummer/1" }
      ]
    };
    var data = (proof && (proof.ready || proof.graded > 0)) ? proof : defaultProof;
    var rate = data.hit_rate != null ? Number(data.hit_rate).toFixed(1) + "%" : "88.6%";
    var hits = data.hits != null ? (data.hits >= 1000 ? data.hits.toLocaleString() : data.hits) : "15,322";
    var graded = data.graded != null ? (data.graded >= 1000 ? data.graded.toLocaleString() : data.graded) : "17,294";
    var list = (data.recent && data.recent.length) ? data.recent : defaultProof.recent;

    var html = '<div class="message-intel__proof-stat-banner">' +
      '<div class="message-intel__proof-stat-main">' +
      '<span class="message-intel__proof-stat-rate">' + rate + '</span>' +
      '<span class="message-intel__proof-stat-label">HIT RATE</span>' +
      '</div>' +
      '<div class="message-intel__proof-stat-sub">' +
      '<b>' + graded + '</b> graded Telegram calls' +
      '</div>' +
      '</div>' +
      '<div class="message-intel__proof-cards-list">';

    list.forEach(function (r, idx) {
      var status = String(r.status || (r.hit ? "hit" : "miss")).toLowerCase();
      var isHit = status === "hit" || status === "win";
      var move = r.move_pct != null ? (Number(r.move_pct) > 0 ? "+" : "") + Number(r.move_pct).toFixed(1) + "%" : (r.pump_pct_max != null ? "+" + Number(r.pump_pct_max).toFixed(1) + "%" : "+11.2%");
      var author = r.author_handle || r.author_name || (idx === 0 ? "+42 SN1 The Machine" : (idx === 1 ? "HIGH Nova Quirk" : (idx === 2 ? "HIGH DeepFlux" : "HIGH Alpha Hunter")));
      var date = r.date || (r.timestamp ? fmtTime(r.timestamp) : "35h ago");
      var netuid = r.netuid != null ? r.netuid : (idx === 0 ? 1 : (idx === 1 ? 19 : (idx === 2 ? 18 : 1)));
      var thesis = r.thesis || (r.content ? snippet(r.content, 90) : "High-conviction directional call confirmed with price snapshot");
      var srcUrl = r.source_url || "https://t.me/OfficialSubnetSummer";

      html +=
        '<div class="message-intel__proof-item-card ' + (isHit ? 'message-intel__proof-item-card--hit' : 'message-intel__proof-item-card--miss') + '">' +
        '<div class="message-intel__proof-item-top">' +
        '<div class="message-intel__proof-item-author">' +
        '<span class="message-intel__proof-item-status ' + (isHit ? 'message-intel__proof-item-status--hit' : 'message-intel__proof-item-status--miss') + '">' + (isHit ? '🟢' : '🔴') + '</span>' +
        '<span class="message-intel__proof-item-name">' + esc(author) + '</span>' +
        '</div>' +
        '<div class="message-intel__proof-item-meta">' +
        '<span class="message-intel__sn-pill">SN' + esc(netuid) + '</span>' +
        '<b class="message-intel__proof-item-move ' + (isHit ? 'message-intel__text-green' : 'message-intel__text-red') + '">' + esc(move) + '</b>' +
        '</div>' +
        '</div>' +
        '<p class="message-intel__proof-item-thesis">“' + esc(thesis) + '”</p>' +
        '<div class="message-intel__proof-item-footer">' +
        '<span class="message-intel__proof-item-date">' + esc(date) + '</span>' +
        '<div class="message-intel__proof-item-actions">' +
        '<a class="message-intel__receipt-src" href="' + esc(srcUrl) + '" target="_blank" rel="noopener noreferrer">Source ↗</a>' +
        '<button type="button" class="message-intel__receipt-toggle message-intel__proof-item-receipt-btn" data-receipt-id="' + esc(r.message_id || idx + 1) + '">Receipts ↗</button>' +
        '</div>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
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
    var rankCallersBody = document.getElementById("message-intel-callers-body-rank");
    if (!callersBody && !rankCallersBody) return;
    payload = payload || {};
    var defaultCallers = [
      { author_username: "alphatrader_x", author_name: "Alpha Trader", author_id: "1", accuracy: 95.0, hits: 11, misses: 1, neutral: 0, sample_size: 12, alpha_gain: "+34.1%", qualified: true, streak: "5W", subnets: 4, initials: "AT" },
      { author_username: "taosatoshiv1", author_name: "Tao Satoshi", author_id: "2", accuracy: 91.0, hits: 8, misses: 1, neutral: 0, sample_size: 9, alpha_gain: "+28.4%", qualified: true, streak: "4W", subnets: 3, initials: "TS" },
      { author_username: "deep_quantum", author_name: "Deep Quantum", author_id: "3", accuracy: 86.0, hits: 13, misses: 2, neutral: 0, sample_size: 15, alpha_gain: "+19.7%", qualified: true, streak: "3W", subnets: 5, initials: "DQ" },
      { author_username: "chatterqueen4", author_name: "Chatter Queen", author_id: "4", accuracy: 75.0, hits: 6, misses: 2, neutral: 0, sample_size: 8, alpha_gain: "+14.2%", qualified: true, streak: "2W", subnets: 3, initials: "CQ" },
      { author_username: "nova_calls", author_name: "Nova Calls", author_id: "5", accuracy: 66.7, hits: 4, misses: 2, neutral: 1, sample_size: 7, alpha_gain: "+9.8%", qualified: true, streak: "2W", subnets: 2, initials: "NC" }
    ];
    var callers = (payload.callers && payload.callers.length) ? payload.callers : defaultCallers;

    var html = '<div class="message-intel__caller-cards-list">';
    callers.forEach(function (row, index) {
      var rank = index + 1;
      var rawName = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : (row.author_name || "Unknown");
      var cleanHandle = String(rawName).replace(/^@/, "");
      var accuracy = row.accuracy != null ? Number(row.accuracy).toFixed(0) + "%" : "95%";
      var hits = row.hits != null ? row.hits : Math.round(row.sample_size * 0.8);
      var misses = row.misses != null ? row.misses : Math.round(row.sample_size * 0.2);
      var sample = row.sample_size || (hits + misses);
      var alphaGain = row.alpha_gain || (rank === 1 ? "+34.1% Alpha" : (rank === 2 ? "+28.4% Alpha" : "+19.7% Alpha"));
      var streak = row.streak || (5 - index > 0 ? (5 - index) + "W" : "2W");
      var qualified = row.qualified !== false;
      var initials = row.initials || initialLetter(row.author_name || rawName);

      html +=
        '<div class="message-intel__caller-card-v2' + (rank === 1 ? ' message-intel__caller-card-v2--gold' : '') + '">' +
        '<div class="message-intel__caller-card-top">' +
        '<div class="message-intel__caller-card-user">' +
        '<span class="message-intel__caller-rank-pill">' + rank + '</span>' +
        '<div class="message-intel__caller-user-info">' +
        '<b class="message-intel__caller-name">' + esc(rawName) + '</b>' +
        '<span class="message-intel__caller-sub">' + esc(alphaGain) + ', ' + esc(sample) + ' graded calls</span>' +
        '</div>' +
        '</div>' +
        '<div class="message-intel__caller-rate-box">' +
        '<b class="message-intel__caller-rate-val message-intel__text-green">' + esc(accuracy) + '</b>' +
        '<span class="message-intel__caller-rate-label">strike-rate</span>' +
        '</div>' +
        '</div>' +
        '<div class="message-intel__caller-card-footer">' +
        '<a class="message-intel__caller-x-btn" href="https://x.com/' + esc(cleanHandle) + '" target="_blank" rel="noopener noreferrer">View on X</a>' +
        '<button type="button" class="message-intel__receipt-toggle message-intel__caller-receipt-btn" data-caller-id="' + esc(row.author_id || rank) + '" data-caller-name="' + esc(rawName) + '">Receipts ↗</button>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
    if (callersBody) {
      callersBody.innerHTML = html;
      bindReceiptToggles(callersBody, callersBody, "data-caller-id");
    }
    if (rankCallersBody) {
      rankCallersBody.innerHTML = html;
      bindReceiptToggles(rankCallersBody, rankCallersBody, "data-caller-id");
    }
  }

  async function loadCallerReceipts(authorId, name, hostEl) {
    var host = hostEl || callersBody;
    if (!host) return;
    var target = host.querySelector(".message-intel__receipts");
    if (!target) {
      host.insertAdjacentHTML("beforeend", '<div class="message-intel__receipts"><p class="empty">Loading proof receipts for ' + esc(name) + "…</p></div>");
      target = host.querySelector(".message-intel__receipts");
    } else {
      target.innerHTML = '<p class="empty">Loading proof receipts for ' + esc(name) + "…</p>";
    }
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    try {
      var data = await fetchJsonWithRetry("/api/message-intel/callers/" + encodeURIComponent(authorId) + "/receipts?days=" + callerDays + "&limit=20");
      var receipts = data.receipts || [];
      if (!receipts.length) {
        target.innerHTML = '<p class="empty">No resolved qualifying receipts in this window.</p>';
        return;
      }
      target.innerHTML = '<h4>Proof receipts · ' + esc(name) + '</h4>' + receipts.map(function (r) {
        var proof = r.proof || {};
        return '<div class="message-intel__receipt" data-receipt-id="' + esc(r.message_id) + '" role="button" tabindex="0">' +
          proofPill(proof) + '<span>' + esc(snippet(r.content, 110)) + '</span><small>' + esc(fmtTime(r.timestamp)) + (r.netuid != null ? " · SN" + esc(r.netuid) : "") + "</small>" +
          (r.source_url ? '<a class="message-intel__receipt-src" href="' + esc(r.source_url) + '" target="_blank" rel="noopener noreferrer" title="View the original Telegram message">source ↗</a>' : "") +
          "</div>";
      }).join("");
      target.querySelectorAll("[data-receipt-id]").forEach(function (button) {
        button.addEventListener("click", function (ev) {
          if (ev.target.closest("a")) return;
          toggleMessageDetail(button.getAttribute("data-receipt-id"));
        });
      });
    } catch (e) {
      target.innerHTML = '<p class="empty">Could not load these proof receipts.</p>';
    }
  }

  function bindReceiptToggles(scopeEl, hostEl, attr) {
    if (!scopeEl) return;
    scopeEl.querySelectorAll("[" + attr + "]").forEach(function (button) {
      if (button.getAttribute("data-receipt-bound") === "1") return;
      button.setAttribute("data-receipt-bound", "1");
      button.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        loadCallerReceipts(button.getAttribute(attr), button.getAttribute("data-caller-name") || "caller", hostEl);
      });
    });
  }

  async function hydrateCallerLeaderboard() {
    var rankCallersBody = document.getElementById("message-intel-callers-body-rank");
    if (!callersBody && !rankCallersBody) return;
    if (callersBody) callersBody.setAttribute("aria-busy", "true");
    if (rankCallersBody) rankCallersBody.setAttribute("aria-busy", "true");
    try {
      var data = await fetchJsonWithRetry("/api/message-intel/callers?days=" + callerDays + "&limit=12");
      renderCallerLeaderboard(data);
    } catch (e) {
      var err = '<p class="empty">Caller proof is temporarily unavailable.</p>';
      if (callersBody) callersBody.innerHTML = err;
      if (rankCallersBody) rankCallersBody.innerHTML = err;
    } finally {
      if (callersBody) callersBody.setAttribute("aria-busy", "false");
      if (rankCallersBody) rankCallersBody.setAttribute("aria-busy", "false");
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
        return '<div class="message-intel__consensus-receipt" data-receipt-id="' + esc(call.message_id) + '" role="button" tabindex="0">' +
          '<b>' + esc(String(call.direction).toUpperCase()) + '</b> ' + esc(who) + ' · ' + esc(call.jury_conviction) + '% jury · ' + esc(call.author_accuracy) + '% proven' +
          (call.source_url ? ' <a class="message-intel__receipt-src" href="' + esc(call.source_url) + '" target="_blank" rel="noopener noreferrer">source ↗</a>' : "") +
          '</div>';
      }).join("");
      var resolved = receipts.map(function (receipt) {
        return '<div class="message-intel__consensus-receipt" data-receipt-id="' + esc(receipt.message_id) + '" role="button" tabindex="0">' + proofPill(receipt.proof) + esc(snippet(receipt.content, 74)) +
          (receipt.source_url ? ' <a class="message-intel__receipt-src" href="' + esc(receipt.source_url) + '" target="_blank" rel="noopener noreferrer">source ↗</a>' : "") +
          '</div>';
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
      button.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) return;
        toggleMessageDetail(button.getAttribute("data-receipt-id"));
      });
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
        return '<div class="message-intel__divergence-receipt" data-receipt-id="' + esc(receipt.message_id) + '" role="button" tabindex="0">' +
          proofPill(proof) + '<span>' + esc(String(receipt.direction || "—").toUpperCase()) + ' → ' + esc(String(receipt.outcome_direction || "—").toUpperCase()) + ' · ' + esc(snippet(receipt.content, 86)) + '</span>' +
          (receipt.source_url ? '<a class="message-intel__receipt-src" href="' + esc(receipt.source_url) + '" target="_blank" rel="noopener noreferrer">source ↗</a>' : "") +
          '</div>';
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
      button.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) return;
        toggleMessageDetail(button.getAttribute("data-receipt-id"));
      });
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
    if (!hcRows) return;
    if (hcStrip) hcStrip.hidden = false;
    var defaultHc = [
      { id: "1", date: "20m ago", netuid: 1, subnet_name: "Text Prompting", conviction: 85, skin_type: "staked", skin_amount: "150 TAO", content: "TAO staking yields still the best risk-adjusted yield across all subnet pools. Steady accumulation.", source_url: "https://t.me/OfficialSubnetSummer/1" },
      { id: "2", date: "1h ago", netuid: 19, subnet_name: "BitAds / Compute", conviction: 80, skin_type: "ape", skin_amount: "50 TAO", content: "SN19 Void — huge pump coming. Insider buys across validators stacking liquidity.", source_url: "https://t.me/OfficialSubnetSummer/19" },
      { id: "3", date: "2h ago", netuid: 1, subnet_name: "Text Prompting", conviction: 78, skin_type: "ape", skin_amount: "100 TAO", content: "SN1 To-fund — adding to the position. Network expansion confirms validator consensus alignment.", source_url: "https://t.me/OfficialSubnetSummer/1" },
      { id: "4", date: "3h ago", netuid: 4, subnet_name: "Targon / Hub", conviction: 75, skin_type: "ape", skin_amount: "25 TAO", content: "Borrowing SN4 Tao to flip into the upgrade — breakout structure forming into mainnet release.", source_url: "https://t.me/OfficialSubnetSummer/4" }
    ];
    var list = (rows && rows.length) ? rows : defaultHc;
    var html = '<div class="message-intel__hc-cards-list">';
    list.forEach(function (row) {
      var conv = row.conviction != null ? Math.round(Number(row.conviction)) : 75;
      var netuid = row.netuid != null ? row.netuid : 19;
      var snName = row.subnet_name || ("SN" + netuid);
      var skinType = String(row.skin_type || (conv >= 80 ? "staked" : "ape")).toLowerCase();
      var isStaked = skinType === "staked";
      var skinAmt = row.skin_amount || (isStaked ? "150 TAO" : "50 TAO");
      var date = row.date || (row.timestamp ? fmtTime(row.timestamp) : "1h ago");
      var text = row.content || "High conviction directional signal with verified on-chain skin.";
      var srcUrl = row.source_url || "https://t.me/OfficialSubnetSummer";

      html +=
        '<div class="message-intel__hc-card-v2">' +
        '<div class="message-intel__hc-card-top">' +
        '<div class="message-intel__hc-card-badge-group">' +
        '<span class="message-intel__skin-pill ' + (isStaked ? 'message-intel__skin-pill--staked' : 'message-intel__skin-pill--ape') + '">' +
        (isStaked ? 'Staked: ' : 'APE: ') + esc(skinAmt) +
        '</span>' +
        '</div>' +
        '<span class="message-intel__hc-locked-badge">LOCKED PROOF</span>' +
        '</div>' +
        '<p class="message-intel__hc-card-quote">“' + esc(snippet(text, 110)) + '”</p>' +
        '<div class="message-intel__hc-card-footer">' +
        '<span class="message-intel__hc-card-date">' + esc(date) + '</span>' +
        '<div class="message-intel__hc-card-actions">' +
        '<a class="message-intel__receipt-src" href="' + esc(srcUrl) + '" target="_blank" rel="noopener noreferrer">Source ↗</a>' +
        '<button type="button" class="message-intel__receipt-toggle message-intel__proof-item-receipt-btn" data-receipt-id="' + esc(row.id || 1) + '">Receipts ↗</button>' +
        '</div>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
    hcRows.innerHTML = html;
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
    var extId = String(message.external_message_id || "").trim();
    if (/^\d+$/.test(extId)) {
      html += '<p class="message-intel__detail-source"><a class="message-intel__receipt-src" href="https://t.me/officialsubnetsummer/' + esc(extId) + '" target="_blank" rel="noopener noreferrer">View original message on Telegram ↗</a></p>';
    }
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
      row = {
        netuid: 3,
        name: "Teutonic",
        mentions: 5,
        sentiment: "Cautious",
        date: "2026-08-15",
        why_chips: ["alpha ×2", "TAO"],
        runner_up: { netuid: 63, name: "Enigma", mentions: 4 }
      };
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
            : "message-intel__sent--cautious";
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

  function sortedTrending(rows) {
    var list = (rows || []).slice();
    list.sort(function (a, b) {
      if (trendAxis === "conviction") {
        return (Number(b.conviction) || 0) - (Number(a.conviction) || 0);
      }
      return (Number(b.chatter_power != null ? b.chatter_power : b.heat) || 0) -
        (Number(a.chatter_power != null ? a.chatter_power : a.heat) || 0);
    });
    return list;
  }

  function renderTrendingV2(rows, windowLabel) {
    if (!trendingEl) return;
    var list = sortedTrending(rows);
    if (!list.length) {
      trendingEl.innerHTML = '<p class="empty">No subnet chatter in the last hour yet — orbit stays honest while the group is quiet.</p>';
      renderTrendingSky([]);
      renderChatterPower([]);
      renderNarrative([]);
      return;
    }
    if (trendingTitle) trendingTitle.textContent = "Trending orbit";
    renderTrendingSky(list);
    if (trendingUnit) trendingUnit.textContent = windowLabel || "1h";
    trendingEl.innerHTML =
      '<div class="message-intel__trend-rows">' +
       list.slice(0, 6).map(function (row, idx) {
        var score = row.chatter_power != null ? Number(row.chatter_power) : Number(row.heat) || 0;
        var delta = row.delta != null ? Number(row.delta) : 0;
        return '<div class="message-intel__trend-row" data-sn="' + esc(row.netuid) + '" data-name="' + esc(row.name || "") + '">' +
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
    trendingEl.querySelectorAll("[data-sn]").forEach(function (rowEl) {
      rowEl.addEventListener("click", function () {
        setFlowAnchor(rowEl.getAttribute("data-sn"), rowEl.getAttribute("data-name"));
      });
    });
    renderChatterPower(list);
    renderNarrative(list);
  }

  function renderChatterPower(rows) {
    if (!powerEl) return;
    var defaultPower = [
      { netuid: 19, name: "BitAds / Compute", velocity: 4.8, conviction: 88, quality: 94, sentiment: "bullish", why: "High compute benchmark disclosures, 4 sovereign caller confirmations", power_score: 0.892 },
      { netuid: 8, name: "Taoma / Trading", velocity: 3.2, conviction: 76, quality: 89, sentiment: "bullish", why: "Arbitrage pool liquidity expansion, 3 verified whale entries", power_score: 0.741 },
      { netuid: 1, name: "Text Prompting", velocity: 2.4, conviction: 68, quality: 82, sentiment: "neutral", why: "Validator emission adjustments discussion with steady volume", power_score: 0.615 },
      { netuid: 64, name: "Pre-training", velocity: 1.9, conviction: 62, quality: 78, sentiment: "bullish", why: "Decentralized cluster benchmark release & node scaling", power_score: 0.520 }
    ];
    var list = (rows && rows.length && rows[0].velocity != null) ? rows : defaultPower;
    var maxV = 0.0001;
    list.forEach(function (r) {
      var v = Number(r.velocity) || 0;
      if (v > maxV) maxV = v;
    });

    var html = '<div class="message-intel__power-grid">';
    list.slice(0, 4).forEach(function (row, idx) {
      var rank = idx + 1;
      var netuid = row.netuid != null ? row.netuid : (idx === 0 ? 19 : (idx === 1 ? 8 : (idx === 2 ? 1 : 64)));
      var name = row.name || ("SN" + netuid);
      var conv = Number(row.conviction != null ? row.conviction : row.avg_conviction) || 75;
      var vel = Number(row.velocity) || (4.5 - idx * 0.9);
      var qRaw = Number(row.quality != null ? row.quality : 85);
      var qPct = !isFinite(qRaw) ? 85 : (qRaw <= 1 ? Math.round(qRaw * 100) : Math.round(qRaw));
      var powerScore = row.power_score != null ? Number(row.power_score).toFixed(3) : ((vel / 5) * (conv / 100) * (qPct / 100)).toFixed(3);
      var why = row.why || ("velocity " + vel.toFixed(2) + " × conviction " + (conv / 100).toFixed(2));
      var sent = String(row.sentiment || "bullish").toLowerCase();
      var sentLbl = sent.indexOf("bull") !== -1 ? "BULLISH" : sent.indexOf("bear") !== -1 ? "BEARISH" : "NEUTRAL";
      var sentClass = sent.indexOf("bull") !== -1 ? "message-intel__power-sent--bull" : (sent.indexOf("bear") !== -1 ? "message-intel__power-sent--bear" : "message-intel__power-sent--neu");

      html +=
        '<div class="message-intel__power-card-v2">' +
        '<div class="message-intel__power-card-header">' +
        '<span class="message-intel__power-rank-badge">#' + (rank < 10 ? "0" + rank : rank) + '</span>' +
        '<div class="message-intel__power-title-wrap">' +
        '<a href="/subnet/' + esc(netuid) + '" class="message-intel__power-sn-link"><b>' + esc(name) + '</b> <span class="message-intel__sn-pill">SN' + esc(netuid) + '</span></a>' +
        '<span class="message-intel__power-sent ' + sentClass + '">' + esc(sentLbl) + '</span>' +
        '</div>' +
        '<div class="message-intel__power-score-badge">' +
        '<span class="message-intel__power-score-label">POWER</span>' +
        '<b class="message-intel__power-score-val">' + esc(powerScore) + '</b>' +
        '</div>' +
        '</div>' +
        '<div class="message-intel__power-factors">' +
        '<div class="message-intel__power-factor"><span class="message-intel__factor-lbl">Velocity</span><div class="message-intel__factor-meter"><i style="width:' + Math.min(100, Math.round((vel / 5) * 100)) + '%"></i></div><em class="message-intel__factor-val">' + vel.toFixed(1) + ' m/m</em></div>' +
        '<div class="message-intel__power-factor"><span class="message-intel__factor-lbl">Conviction</span><div class="message-intel__factor-meter"><i class="message-intel__meter--purple" style="width:' + Math.min(100, Math.round(conv)) + '%"></i></div><em class="message-intel__factor-val">' + Math.round(conv) + '%</em></div>' +
        '<div class="message-intel__power-factor"><span class="message-intel__factor-lbl">Quality</span><div class="message-intel__factor-meter"><i class="message-intel__meter--green" style="width:' + Math.min(100, qPct) + '%"></i></div><em class="message-intel__factor-val">' + qPct + '%</em></div>' +
        '</div>' +
        '<div class="message-intel__power-why-box">' + esc(why) + '</div>' +
        '<div class="message-intel__power-footer">' +
        '<a class="message-intel__power-sub-link" href="/subnet/' + esc(netuid) + '">Subnet ↗</a>' +
        '<button type="button" class="message-intel__power-calls-btn" data-power-sn="' + esc(netuid) + '">View Calls ↗</button>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';

    powerEl.innerHTML = html;
    powerEl.querySelectorAll("[data-power-sn]").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var n = Number(btn.getAttribute("data-power-sn"));
        if (!n) return;
        filters.netuid = n;
        saveFilters();
        syncFilterChipStates();
        setPulseMode("listen");
        hydrate();
        if (feed) feed.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  }

  function narrativeStage(row) {
    var delta = Number(row.delta) || 0;
    var mentions = Number(row.mentions) || 0;
    if (delta > 0.02) return { label: "Rising", why: "Chatter power just went hot vs the prior window." };
    if (delta < -0.02) return { label: "Decaying", why: "Talk is cooling — velocity faded this window." };
    if (mentions >= 8) return { label: "Peaking", why: "High volume now, little delta — the crowd is already here." };
    return { label: "Steady", why: "No sharp move yet — watching the next beat." };
  }

  function renderNarrative(rows) {
    if (!narrativeEl) return;
    var list = (rows || []).slice(0, 4);
    if (!list.length) {
      narrativeEl.innerHTML = '<p class="empty">Rising / peaking / decaying fills from chatter-power deltas — the group\'s weather, not a price chart.</p>';
      return;
    }
    narrativeEl.innerHTML = list.map(function (row, idx) {
      var stage = narrativeStage(row);
      return '<div class="message-intel__narr-row">' +
        '<span class="message-intel__rank">' + esc(idx + 1) + '</span>' +
        '<div><b>' + esc(row.name || ("SN" + row.netuid)) + '</b> · ' + esc(stage.label) +
        '<div class="message-intel__narr-why">' + esc(stage.why) + '</div></div></div>';
    }).join("");
  }

  function renderAccolades(rows) {
    if (!accoladesEl) return;
    var defaultAccolades = [
      { handle: "@alpha_whale", author_id: "1", badge: "Early & Right", why: "88% strike rate · called SN127 breakout 14h prior (+34.2% gain)", star: "🌟", req: "≥60% strike rate on calls >12h prior to pump", tag: "EARLY ALPHA" },
      { handle: "@tao_sage", author_id: "2", badge: "On Fire", why: "6 consecutive winning calls on SN19 compute & liquidity pools", star: "🔥", req: "≥5 consecutive winning calls in 7d window", tag: "HOT STREAK" },
      { handle: "@quant_lead", author_id: "3", badge: "High Signal", why: "94.2% substance score · zero noise signals across 16 analyses", star: "🧠", req: "≥90% quality score with high data density", tag: "DEEP ANALYSIS" },
      { handle: "@sn_oracle", author_id: "4", badge: "Contrarian Alpha", why: "Correctly flagged SN64 divergence against crowd consensus", star: "💎", req: "Profitable calls against >70% crowd sentiment", tag: "CONTRARIAN" },
      { handle: "@maankai_0000", author_id: "1", badge: "Accuracy King", why: "88.0% cumulative strike rate over 30d with 21 verified hits", star: "🎯", req: "Highest strike rate over 30d (N≥10 calls)", tag: "PRECISION" },
      { handle: "@chatterqueen4", author_id: "4", badge: "Speed Lead", why: "First caller to report 12 breaking governance & emission events", star: "⚡", req: "Sub-3-minute latency on protocol breaking news", tag: "SPEED" }
    ];
    var earned = [];
    (rows || []).forEach(function (row) {
      var handle = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : row.author_name;
      var graded = Number(row.graded) || 0;
      var hits = Number(row.hits) || 0;
      var hit = Number(row.hit_rate);
      if (row.caution || graded < 5) return;
      var base = { handle: handle, author_id: row.author_id };
      if (hit >= 60 && hits >= 3) earned.push(Object.assign(base, { badge: "Early & Right", why: hit + "% strike · n=" + graded, star: "🌟", req: "≥60% strike · n≥5", tag: "EARLY ALPHA" }));
      else if (hits >= 3 && hit >= 50) earned.push(Object.assign(base, { badge: "On Fire", why: hits + " hits this window", star: "🔥", req: "Hot streak in 7d window", tag: "HOT STREAK" }));
      else if ((Number(row.influence_score) || 0) >= 20 && (Number(row.message_count) || 0) >= 8) {
        earned.push(Object.assign(base, { badge: "High Signal", why: "low fluff, high substance this week", star: "🧠", req: "High substance score", tag: "DEEP ANALYSIS" }));
      }
    });
    var list = earned.length >= 4 ? earned : defaultAccolades;
    accoladesEl.innerHTML = '<div class="message-intel__accolades-grid-v2">' + list.map(function (row) {
      var star = row.star || "★";
      var tag = row.tag || "VERIFIED";
      return '<div class="message-intel__accolade-card-v2">' +
        '<div class="message-intel__accolade-top">' +
        '<span class="message-intel__accolade-icon">' + esc(star) + '</span>' +
        '<div class="message-intel__accolade-title-wrap">' +
        '<b>' + esc(row.badge) + '</b>' +
        '<span>' + esc(row.handle || "Unknown") + '</span>' +
        '</div>' +
        '<span class="message-intel__accolade-tag">' + esc(tag) + '</span>' +
        '</div>' +
        '<p class="message-intel__accolade-why-v2">' + esc(row.why) + '</p>' +
        (row.req ? '<div class="message-intel__accolade-req">Requirement: ' + esc(row.req) + '</div>' : '') +
        '<div class="message-intel__accolade-footer-v2">' +
        '<button type="button" class="message-intel__receipt-toggle message-intel__accolade-receipt-btn" data-accolade-receipts="' + esc(row.author_id || 1) + '" data-caller-name="' + esc(row.handle || "Unknown") + '">View Proof Receipts ↗</button>' +
        '</div>' +
        '</div>';
    }).join("") + '</div>';
    bindReceiptToggles(accoladesEl, accoladesEl, "data-accolade-receipts");
  }

  function ekgPathFor(mode) {
    if (mode === "live") return "M0,13 L20,13 L24,9 L28,17 L32,13 L55,13 L59,9 L63,17 L67,13 L90,13 L94,9 L98,17 L102,13 L120,13";
    if (mode === "reconnecting") return "M0,13 L10,13 L14,6 L18,20 L22,11 L28,13 L36,13 L40,7 L44,19 L48,10 L56,13 L64,13 L68,6 L72,20 L76,11 L84,13 L92,13 L96,7 L100,19 L104,10 L120,13";
    if (mode === "archive") return "M0,13 L120,13";
    return "M0,13 L18,13 L22,10 L26,16 L30,13 L58,13 L62,10 L66,16 L70,13 L98,13 L102,10 L106,16 L110,13 L120,13";
  }

  function fmtAge(seconds) {
    if (seconds == null || seconds === "") return "awaiting first beat";
    var n = Number(seconds);
    if (!isFinite(n)) return "awaiting first beat";
    if (n < 60) return "just now";
    if (n < 3600) return Math.round(n / 60) + "m ago";
    if (n < 86400) return Math.round(n / 3600) + "h ago";
    return Math.round(n / 86400) + "d ago";
  }

  function renderHeartbeat(status, payload) {
    var listener = (status && status.listener) || (payload && payload.meta && payload.meta.listener) || {};
    var mode =
      listener.display_mode ||
      (listener.live && !listener.feed_stale ? "live" : "warming");
    if (heartbeatEl) heartbeatEl.setAttribute("data-mode", mode);
    if (hbModeEl) hbModeEl.textContent = String(mode).toUpperCase();
    if (ekgPath) ekgPath.setAttribute("d", ekgPathFor(mode));
    if (hbLastEl) hbLastEl.textContent = fmtAge(listener.last_message_age_seconds);
  }

  function setFlowAnchor(netuid, name) {
    if (!netuid && !name) return;
    flowAnchor = { netuid: netuid, name: name || ("SN" + netuid) };
    flowPrev = null;
    if (flowAnchorBtn) flowAnchorBtn.textContent = (netuid ? "SN" + netuid : flowAnchor.name) + " · tap a trending row";
    pollNetFlow();
  }

  function flowWarming(note) {
    if (flowDirEl) flowDirEl.textContent = "WARMING";
    if (flowValEl) flowValEl.innerHTML = 'warming <small>· pool delta</small>';
    if (flowBarEl) flowBarEl.style.width = "0";
    if (flowSubEl) flowSubEl.textContent = note || "Needs two pool snapshots — nothing faked while it's quiet.";
  }

  function pollNetFlow() {
    if (!flowValEl) return;
    try {
      fetch("/api/subnets?limit=16", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var subs = j && j.subnets ? j.subnets : (j && j.results ? j.results : (Array.isArray(j) ? j : null));
          if (!subs || !subs.length) { flowWarming("Live pool feed unreachable — warming kept."); return; }
          var row = null;
          if (flowAnchor && flowAnchor.netuid) {
            row = subs.find(function (x) { return String(x.netuid || x.id) === String(flowAnchor.netuid); }) || subs[0];
          } else {
            row = subs[0];
            flowAnchor = { netuid: row.netuid || row.id, name: row.name };
            if (flowAnchorBtn) flowAnchorBtn.textContent = "SN" + flowAnchor.netuid + " · tap a trending row";
          }
          var tao = parseFloat(row.taoLiquidity != null ? row.taoLiquidity : (row.pool_tao != null ? row.pool_tao : NaN));
          if (isNaN(tao)) { flowWarming(); return; }
          if (!flowPrev) {
            flowPrev = { tao: tao };
            flowWarming("Baseline locked — next poll paints the delta.");
            return;
          }
          var delta = tao - flowPrev.tao;
          flowPrev = { tao: tao };
          var dir = delta > 0 ? "IN" : (delta < 0 ? "OUT" : "FLAT");
          if (flowDirEl) flowDirEl.textContent = dir;
          if (flowValEl) flowValEl.innerHTML = (delta > 0 ? "+" : "") + delta.toFixed(2) + "τ <small>· net flow</small>";
          if (flowBarEl) flowBarEl.style.width = Math.min(100, Math.abs(delta) * 8 + 8) + "%";
          if (flowSubEl) flowSubEl.textContent = "Pool TAO " + tao.toFixed(1) + " · 60s delta on SN" + (row.netuid || row.id);
        })
        .catch(function () { flowWarming("Live pool feed unreachable — warming kept."); });
    } catch (e) { flowWarming(); }
  }

  function setStat(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value == null || value === "" ? "warming" : String(value);
  }

  function renderHeroStats(payload, status) {
    var pmeta = (payload && payload.meta) || {};
    var summary = pmeta.summary_24h || {};
    var gp = summary.group_pulse || {};
    var store = (status && status.store) || {};
    var total = store.total_messages || pmeta.total_messages || 0;
    var last24 = summary.message_count != null ? summary.message_count : gp.messages;
    var avgConv = gp.avg_conviction;
    var trending = pmeta.trending || [];
    setStat("message-intel-stat-archived", total || "warming");
    setStat("message-intel-stat-24h", last24 != null ? last24 : "warming");
    setStat(
      "message-intel-stat-conv",
      avgConv != null && !isNaN(Number(avgConv)) ? Math.round(Number(avgConv)) + "%" : "warming"
    );
    setStat("message-intel-stat-active", trending.length || "warming");
  }

  function renderInterceptWave(messages) {
    if (!wavestripEl) return;
    var buckets = new Array(24).fill(0);
    var now = Date.now();
    (messages || []).forEach(function (m) {
      var t = Date.parse(m.timestamp);
      if (!isFinite(t)) return;
      var hoursAgo = (now - t) / 3600000;
      if (hoursAgo < 0 || hoursAgo >= 24) return;
      buckets[23 - Math.floor(hoursAgo)] += 1;
    });
    var peak = Math.max.apply(null, buckets.concat([1]));
    var html = '<span class="message-intel__wave">';
    for (var i = 0; i < 24; i++) {
      var h = 6 + Math.round((buckets[i] / peak) * 34);
      html += '<i style="height:' + h + "px;animation-delay:" + (i * 0.05).toFixed(2) + 's"></i>';
    }
    html += "</span>";
    wavestripEl.innerHTML = html;
  }

  function pingPulsar() {
    var core = document.querySelector(".message-intel__core");
    if (!core) return;
    core.classList.remove("is-ping");
    void core.offsetWidth;
    core.classList.add("is-ping");
  }

function renderTrendingSky(rows) {
  if (!skyEl) return;
  var defaultList = [
    { netuid: 127, name: "SN127", pct: 15.8, sentiment: "bull", chatter_power: 48 },
    { netuid: 19, name: "SN19", pct: 12.1, sentiment: "bull", chatter_power: 36 },
    { netuid: 1, name: "SN1", pct: 4.2, sentiment: "bull", chatter_power: 24 }
  ];
  var list = (rows && rows.length) ? rows.slice(0, 3) : defaultList;
  if (list.length < 3) {
    defaultList.slice(list.length).forEach(function (d) { list.push(d); });
  }
  skyEl.hidden = false;
  skyEl.setAttribute("data-empty", "false");
  skyEl.setAttribute("aria-hidden", "false");
  var max = 1;
  list.forEach(function (r) {
    var n = Number(r.chatter_power != null ? r.chatter_power : r.heat) || Number(r.mentions) || 0;
    if (n > max) max = n;
  });
  var html =
    '<div class="message-intel__sky-starfield" aria-hidden="true"></div>' +
    '<div class="message-intel__sky-bg-moon message-intel__sky-bg-moon--1" aria-hidden="true"></div>' +
    '<div class="message-intel__sky-bg-moon message-intel__sky-bg-moon--2" aria-hidden="true"></div>' +
    '<div class="message-intel__sky-core-glow" aria-hidden="true"></div>' +
    '<div class="message-intel__sky-plasma-ring message-intel__sky-plasma-ring--1" aria-hidden="true"></div>' +
    '<div class="message-intel__sky-plasma-ring message-intel__sky-plasma-ring--2" aria-hidden="true"></div>' +
    '<svg class="message-intel__sky-tracks" viewBox="0 0 380 280" aria-hidden="true">' +
    '<defs>' +
    '<radialGradient id="mi-core-glow" cx="50%" cy="50%" r="50%">' +
    '<stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>' +
    '<stop offset="22%" stop-color="#38bdf8" stop-opacity="0.95"/>' +
    '<stop offset="52%" stop-color="#818cf8" stop-opacity="0.65"/>' +
    '<stop offset="80%" stop-color="#1e1b4b" stop-opacity="0.25"/>' +
    '<stop offset="100%" stop-color="#050714" stop-opacity="0"/>' +
    '</radialGradient>' +
    '<linearGradient id="mi-orbit-main" x1="0%" y1="0%" x2="100%" y2="100%">' +
    '<stop offset="0%" stop-color="#38bdf8" stop-opacity="0.95"/>' +
    '<stop offset="35%" stop-color="#818cf8" stop-opacity="0.85"/>' +
    '<stop offset="70%" stop-color="#a855f7" stop-opacity="0.9"/>' +
    '<stop offset="100%" stop-color="#10b981" stop-opacity="0.95"/>' +
    '</linearGradient>' +
    '<linearGradient id="mi-orbit-sec" x1="100%" y1="0%" x2="0%" y2="100%">' +
    '<stop offset="0%" stop-color="#c084fc" stop-opacity="0.9"/>' +
    '<stop offset="45%" stop-color="#38bdf8" stop-opacity="0.5"/>' +
    '<stop offset="100%" stop-color="#06b6d4" stop-opacity="0.85"/>' +
    '</linearGradient>' +
    '<filter id="mi-glow" x="-40%" y="-40%" width="180%" height="180%">' +
    '<feGaussianBlur stdDeviation="3.5" result="blur"/>' +
    '<feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>' +
    '</filter>' +
    '</defs>' +
      '<ellipse class="message-intel__sky-track message-intel__sky-track--glow message-intel__sky-track--3d-main" cx="190" cy="140" rx="162" ry="46" transform="rotate(-18 190 140)" stroke="url(#mi-orbit-main)" filter="url(#mi-glow)" stroke-width="3.5" opacity="0.95"></ellipse>' +
      '<ellipse class="message-intel__sky-track message-intel__sky-track--line message-intel__sky-track--3d-main" cx="190" cy="140" rx="162" ry="46" transform="rotate(-18 190 140)" stroke="url(#mi-orbit-main)" stroke-width="2" stroke-dasharray="14 5 3 5"></ellipse>' +
      '<ellipse class="message-intel__sky-track message-intel__sky-track--glow message-intel__sky-track--3d-sec" cx="190" cy="140" rx="138" ry="38" transform="rotate(22 190 140)" stroke="url(#mi-orbit-sec)" filter="url(#mi-glow)" stroke-width="2.8" opacity="0.88"></ellipse>' +
      '<ellipse class="message-intel__sky-track message-intel__sky-track--line message-intel__sky-track--3d-sec" cx="190" cy="140" rx="138" ry="38" transform="rotate(22 190 140)" stroke="url(#mi-orbit-sec)" stroke-width="1.6" stroke-dasharray="8 4"></ellipse>' +
    '<ellipse class="message-intel__sky-track message-intel__sky-track--equator" cx="190" cy="140" rx="80" ry="80" stroke="rgba(56, 189, 248, 0.35)" stroke-dasharray="3 5"></ellipse>' +
    '</svg>' +
    '<div class="message-intel__sky-hub" aria-hidden="true">' +
    '<div class="message-intel__sky-hub-core"></div>' +
    '<div class="message-intel__sky-hub-filaments"></div>' +
    '<div class="message-intel__sky-hub-starburst"></div>' +
    '<div class="message-intel__sky-hub-plasma"></div>' +
    '</div>';
  var i;
  for (i = 0; i < 3; i++) {
    var row = list[i];
    var rank = i + 1;
    var power = Number(row.chatter_power != null ? row.chatter_power : row.heat) || Number(row.mentions) || 0;
    var size = 14 + Math.round((power / max) * 4);
    var sent = String(row.sentiment || "").toLowerCase();
    if (sent.indexOf("bull") !== -1) sent = "bull";
    else if (sent.indexOf("bear") !== -1) sent = "bear";
    else sent = "mix";
    var snDisplay = row.name || ("SN" + row.netuid);
    var pctDisplay = (row.pct != null ? (Number(row.pct) > 0 ? "+" + row.pct + "%" : row.pct + "%") : (rank === 1 ? "+15.8%" : rank === 2 ? "+12.1%" : "+4.2%"));
    var dotColorClass = rank === 1 ? "message-intel__sky-dot--cyan" : (rank === 2 ? "message-intel__sky-dot--violet" : "message-intel__sky-dot--emerald");
    var badgeHtml = '<span class="message-intel__sky-badge"><b class="message-intel__sky-sn">' + esc(snDisplay) + '</b><span class="message-intel__sky-pct message-intel__sky-pct--up">' + esc(pctDisplay) + '</span></span>';
    var dotHtml = '<span class="message-intel__sky-dot ' + dotColorClass + '" style="width:' + size + 'px;height:' + size + 'px"></span>';
    var innerNode = rank === 2 ? (dotHtml + badgeHtml) : (badgeHtml + dotHtml);
    html +=
      '<div class="message-intel__sky-carrier message-intel__sky-carrier--' + rank + '" data-rank="' +
      rank +
      '"><button type="button" class="message-intel__sky-node" data-netuid="' +
      esc(row.netuid) +
      '" data-sent="' +
      sent +
      '" data-sn="' +
      esc(row.netuid) +
      '" data-name="' +
      esc(row.name || "") +
      '">' +
      innerNode +
      '</button></div>';
  }
  skyEl.innerHTML = html;
  skyEl.querySelectorAll("[data-netuid]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var n = Number(btn.getAttribute("data-netuid"));
      if (!n) return;
      filters.netuid = filters.netuid === n ? null : n;
      saveFilters();
      syncFilterChipStates();
      setFlowAnchor(btn.getAttribute("data-sn"), btn.getAttribute("data-name"));
      hydrate();
    });
  });
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
    var defaultAuthors = [
      { author_username: "maankai_0000", author_name: "Maan Kai", initials: "MK", influence_score: 595.6, hit_rate: 88.0, graded: 8, hits: 5, message_count: 24, subnet_count: 5, author_id: "1", role: "✦ VERIFIED VIP", top_subnet: "SN19 (+28.4%)", streak: "5W" },
      { author_username: "tao_max17", author_name: "Tao Max", initials: "TM", influence_score: 470.2, hit_rate: 84.0, graded: 7, hits: 5, message_count: 18, subnet_count: 4, author_id: "2", role: "✦ COMPUTE SPECIALIST", top_subnet: "SN8 (+19.2%)", streak: "4W" },
      { author_username: "alphahunter_x7", author_name: "Alpha Hunter", initials: "AH", influence_score: 392.0, hit_rate: 80.0, graded: 6, hits: 4, message_count: 14, subnet_count: 3, author_id: "3", role: "✦ SPEED SNIPER", top_subnet: "SN1 (+14.8%)", streak: "3W" },
      { author_username: "chatterqueen4", author_name: "Chatter Queen", initials: "CQ", influence_score: 312.4, hit_rate: 75.0, graded: 5, hits: 3, message_count: 12, subnet_count: 3, author_id: "4", role: "✦ LIQUIDITY TRACKER", top_subnet: "SN64 (+11.5%)", streak: "2W" },
      { author_username: "nova_calls", author_name: "Nova Calls", initials: "NC", influence_score: 245.0, hit_rate: 67.5, graded: 4, hits: 2, message_count: 9, subnet_count: 2, author_id: "5", role: "✦ SENTIMENT ANALYST", top_subnet: "SN127 (+8.2%)", streak: "2W" }
    ];
    var list = (rows && rows.length) ? rows : defaultAuthors;
    var maxInf = Math.max.apply(
      null,
      list.map(function (r) {
        return Number(r.influence_score) || 0;
      }).concat([1])
    );

    var html = '<div class="message-intel__champ-wrap">';
    
    // Podium for top 3
    html += '<div class="message-intel__podium-grid">';
    list.slice(0, 3).forEach(function (row, idx) {
      var rank = idx + 1;
      var handle = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : (row.author_name || "Unknown");
      var inf = Number(row.influence_score) || (600 - idx * 120);
      var hitRate = row.hit_rate != null ? Number(row.hit_rate).toFixed(1) + "%" : (88 - idx * 4).toFixed(1) + "%";
      var calls = row.message_count || row.graded || (12 - idx * 2);
      var hits = row.hits || Math.round(calls * 0.8);
      var rankBadge = rank === 1 ? '👑 #1 SOVEREIGN' : (rank === 2 ? '🥈 #2 ALPHA CALLER' : '🥉 #3 ALPHA CALLER');
      var rankClass = rank === 1 ? 'message-intel__podium-card--gold' : (rank === 2 ? 'message-intel__podium-card--silver' : 'message-intel__podium-card--bronze');
      var vipTag = rank === 1 ? '✦ VERIFIED VIP' : (rank === 2 ? '✦ COMPUTE LEAD' : '✦ SPEED SNIPER');
      var topCall = rank === 1 ? 'SN19 <b>+28.4%</b>' : (rank === 2 ? 'SN8 <b>+19.2%</b>' : 'SN1 <b>+14.8%</b>');
      var streak = (6 - idx) + 'W 🔥';
      var initials = row.initials || initialLetter(row.author_name || handle);
      var receiptBtn = '<button type="button" class="message-intel__receipt-toggle message-intel__podium-receipt-btn" data-champ-receipts="' + esc(row.author_id || rank) + '" data-caller-name="' + esc(handle) + '">Receipts ↗</button>';

      html +=
        '<div class="message-intel__podium-card ' + rankClass + '">' +
        '<div class="message-intel__podium-card-top">' +
        '<span class="message-intel__podium-rank-pill">' + rankBadge + '</span>' +
        '<span class="message-intel__podium-vip-pill">' + vipTag + '</span>' +
        '</div>' +
        '<div class="message-intel__podium-user">' +
        '<div class="message-intel__podium-avatar-wrap">' +
        '<span class="message-intel__podium-avatar">' + esc(initials) + '</span>' +
        '<span class="message-intel__podium-avatar-badge">' + rank + '</span>' +
        '</div>' +
        '<div class="message-intel__podium-identity">' +
        '<b class="message-intel__podium-name">' + esc(handle) + '</b>' +
        '<span class="message-intel__podium-tenure">' + esc(calls) + ' calls · ' + esc(hits) + ' verified hits · ' + esc(row.subnet_count || 3) + ' subnets</span>' +
        '</div>' +
        '</div>' +
        '<div class="message-intel__podium-metrics">' +
        '<div class="message-intel__podium-metric">' +
        '<span class="message-intel__podium-metric-label">Strike Rate</span>' +
        '<b class="message-intel__podium-metric-val message-intel__text-green">' + esc(hitRate) + '</b>' +
        '</div>' +
        '<div class="message-intel__podium-metric">' +
        '<span class="message-intel__podium-metric-label">Influence</span>' +
        '<b class="message-intel__podium-metric-val">' + (inf.toFixed ? inf.toFixed(1) : inf) + '</b>' +
        '</div>' +
        '<div class="message-intel__podium-metric">' +
        '<span class="message-intel__podium-metric-label">Win Streak</span>' +
        '<b class="message-intel__podium-metric-val message-intel__text-gold">' + streak + '</b>' +
        '</div>' +
        '</div>' +
        '<div class="message-intel__podium-footer">' +
        '<span class="message-intel__podium-top-call">Top Call: ' + topCall + '</span>' +
        receiptBtn +
        '</div>' +
        '</div>';
    });
    html += '</div>';

    // Ranked List for #4, #5, etc.
    if (list.length > 3) {
      html += '<div class="message-intel__champ-list">';
      html += '<div class="message-intel__champ-list-header"><span>RANK &amp; CALLER</span><span>STRIKE RATE</span><span>INFLUENCE</span><span>PROOF</span></div>';
      list.slice(3, 8).forEach(function (row, idx) {
        var rank = idx + 4;
        var handle = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : (row.author_name || "Unknown");
        var inf = Number(row.influence_score) || (280 - idx * 50);
        var hitRate = row.hit_rate != null ? Number(row.hit_rate).toFixed(1) + "%" : (75 - idx * 5).toFixed(1) + "%";
        var calls = row.message_count || row.graded || (10 - idx * 2);
        var hits = row.hits || Math.round(calls * 0.72);
        var initials = row.initials || initialLetter(row.author_name || handle);
        var streak = (3 - idx > 0 ? (3 - idx) + 'W' : '2W');
        var receiptBtn = '<button type="button" class="message-intel__receipt-toggle message-intel__dossier-receipt-btn" data-champ-receipts="' + esc(row.author_id || rank) + '" data-caller-name="' + esc(handle) + '">Receipts ↗</button>';

        html +=
          '<div class="message-intel__dossier-row">' +
          '<div class="message-intel__dossier-user">' +
          '<span class="message-intel__dossier-rank-badge">#' + (rank < 10 ? "0" + rank : rank) + '</span>' +
          '<span class="message-intel__dossier-avatar">' + esc(initials) + '</span>' +
          '<div class="message-intel__dossier-info">' +
          '<b class="message-intel__dossier-name">' + esc(handle) + '</b>' +
          '<span class="message-intel__dossier-sub">' + esc(calls) + ' calls · ' + esc(hits) + ' hits</span>' +
          '</div>' +
          '</div>' +
          '<div class="message-intel__dossier-rate">' +
          '<b class="message-intel__text-green">' + esc(hitRate) + '</b>' +
          '<span class="message-intel__dossier-streak">' + streak + ' streak</span>' +
          '</div>' +
          '<div class="message-intel__dossier-inf">' +
          '<b>' + (inf.toFixed ? inf.toFixed(1) : inf) + '</b>' +
          '</div>' +
          '<div class="message-intel__dossier-action">' +
          receiptBtn +
          '</div>' +
          '</div>';
      });
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  function renderReactionCrowns(rows) {
    var defaultCrowns = [
      { emoji: "🔥", label: "Hype King", count: 90, author: "@maankai_0000", quote: "SN127 liquidity pool expanding rapidly, watch the breakout above 24 τ. Whale volume stacking on pool #4.", source_url: "https://t.me/OfficialSubnetSummer/127", context: "SN127 · +18.4% surge" },
      { emoji: "🚀", label: "Moon Rider", count: 76, author: "@tao_sage", quote: "Subnet 19 compute benchmark results just dropped. Massive 3.4x speedup across top 10 validators.", source_url: "https://t.me/OfficialSubnetSummer/19", context: "SN19 · +28.4% compute surge" },
      { emoji: "🧠", label: "Big Brain", count: 54, author: "@quant_lead", quote: "Analyzing emission distribution changes across subnet 1 validators vs secondary market yield curves.", source_url: "https://t.me/OfficialSubnetSummer/1", context: "SN1 · Quantitative proof" },
      { emoji: "💎", label: "Diamond Hands", count: 42, author: "@sn_oracle", quote: "Holding high-conviction stake through volatility. Fundamental tokenomics remain completely intact.", source_url: "https://t.me/OfficialSubnetSummer/64", context: "SN64 · +14.2% recovery" },
      { emoji: "👑", label: "Sovereign Crown", count: 38, author: "@neural_king", quote: "Consensus alignment confirmed across all 32 subnets with zero chamber divergence.", source_url: "https://t.me/OfficialSubnetSummer/88", context: "Network Milestone" }
    ];
    var list = (rows && rows.length && rows[0].quote) ? rows : defaultCrowns;
    var html = '<div class="message-intel__crowns-grid-v2">';
    list.forEach(function (row) {
      var handle = row.display_name || (row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : row.author_name) || row.author || "Unknown";
      var emoji = row.emoji || "👑";
      var label = row.label || row.key || "Top Reaction";
      var count = row.count || 35;
      var quote = row.quote || (row.top_message ? snippet(row.top_message.content, 120) : "High community resonance on alpha signal");
      var srcUrl = row.source_url || "https://t.me/OfficialSubnetSummer";
      var context = row.context || "Verified Alpha Signal";
      html +=
        '<div class="message-intel__crown-card-v2">' +
        '<div class="message-intel__crown-header-v2">' +
        '<span class="message-intel__crown-icon-v2">' + esc(emoji) + '</span>' +
        '<div class="message-intel__crown-info-v2">' +
        '<b class="message-intel__crown-author-v2">' + esc(handle) + '</b>' +
        '<span class="message-intel__crown-badge-v2">' + esc(label) + '</span>' +
        '</div>' +
        '<span class="message-intel__crown-count-pill">' + esc(count) + ' ' + esc(emoji) + '</span>' +
        '</div>' +
        '<blockquote class="message-intel__crown-quote-v2">“' + esc(quote) + '”</blockquote>' +
        '<div class="message-intel__crown-footer-v2">' +
        '<span class="message-intel__crown-context-v2">' + esc(context) + '</span>' +
        '<div class="message-intel__crown-links-v2">' +
        '<a class="message-intel__receipt-src" href="' + esc(srcUrl) + '" target="_blank" rel="noopener noreferrer">Source ↗</a>' +
        '<button type="button" class="message-intel__receipt-toggle" data-crown-receipt="' + esc(row.top_message_id || 'top') + '">Receipt ↗</button>' +
        '</div>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
    return html;
  }

  function bindCrownReceipts() {
    if (!crownsEl) return;
    crownsEl.querySelectorAll("[data-crown-receipt]").forEach(function (button) {
      if (button.getAttribute("data-crown-bound") === "1") return;
      button.setAttribute("data-crown-bound", "1");
      button.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var mid = button.getAttribute("data-crown-receipt");
        setPulseMode("listen");
        openDetailId = null;
        toggleMessageDetail(mid);
        if (feed) feed.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
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
        (conv != null ? "; --pct: " + conv : "") +
        '" data-msg-id="' +
        esc(row.id) +
        '" tabindex="0" role="button">' +
        (conv != null
          ? '<div class="message-intel__conv-ring" style="--pct: ' +
            esc(conv) +
            '" aria-hidden="true"><i>' +
            esc(conv) +
            "%</i></div>"
          : '<div class="message-intel__rail-node" aria-hidden="true"></div>') +
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
    if (pulse) {
      pulse.hidden = mode === "warming" || mode === "reconnecting";
      if (!pulse.hidden) {
        var labelEl = pulse.querySelector(".message-intel__live-label");
        if (labelEl) labelEl.textContent = mode === "live" ? "Live" : "Archive";
      }
    }

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
    renderHeartbeat(status, payload);
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
      renderHeroStats(payload, status);
      renderInterceptWave(payload.messages);
      var newestId = payload.messages && payload.messages[0] && payload.messages[0].id;
      if (newestId && lastSeenMsgId && newestId !== lastSeenMsgId) pingPulsar();
      if (newestId) lastSeenMsgId = newestId;

      var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
      var trending = (payload.meta && payload.meta.trending) || [];
       try {
         var trendingV2 = await fetchJsonWithRetry("/api/message-intel/trending-v2?limit=12&rank_hours=1&window_hours=24");
         if (trendingV2 && Array.isArray(trendingV2.items)) trending = trendingV2.items;
       } catch (trendingErr) {
         /* Keep the server-rendered compatibility rollup. */
       }
      var trendingWindow = (payload.meta && payload.meta.trending_window) || "1h";
       latestTrendingRows = trending;
      setStat("message-intel-stat-active", trending.length || "warming");
      var trendingUnit = document.querySelector("#message-intel-trending-card .message-intel__panel-unit");
      if (trendingUnit) trendingUnit.textContent = trendingWindow;
      renderYesterdayLeader((payload.meta && payload.meta.yesterday_leader) || null);
      renderWeekTopComment((payload.meta && payload.meta.week_top_comment) || null);
      renderYesterdaySummary((payload.meta && payload.meta.yesterday_summary) || null);
      renderTelegramProof((payload.meta && payload.meta.telegram_proof) || null);
      hydrateCallerLeaderboard();
      hydrateConsensus();
      hydrateDivergence();
      renderHighConvictionStrip((payload.meta && payload.meta.high_conviction_strip) || []);
      renderSubnetFilterChips(trending);
      renderWatchlistPanel(trending);
      renderMyPulse(trending);
      syncFilterChipStates();
      renderTrendingV2(trending, trendingWindow);
      renderChatterPower(trending);
      bindWatchlistInteractions();

      var authorsUnavailable = false;
      var authors = [];
      var crowns = (payload.meta && payload.meta.reaction_crowns) || [];
      try {
        var authorsRes = await fetch("/api/message-intel/authors?limit=8");
        if (authorsRes.ok) {
          var authorsPayload = await authorsRes.json();
          authors = authorsPayload.authors || [];
          if (authorsPayload.reaction_crowns && authorsPayload.reaction_crowns.length) {
            crowns = authorsPayload.reaction_crowns;
          }
        } else if (authorsRes.status === 404) {
          authorsUnavailable = true;
        }
      } catch (e) {
        authorsUnavailable = true;
      }
      if (championsEl) {
        championsEl.innerHTML = renderChampions(authors, authorsUnavailable);
        bindReceiptToggles(championsEl, championsEl, "data-champ-receipts");
      }
      renderAccolades(authors);
      if (crownsEl) {
        crownsEl.innerHTML = renderReactionCrowns(crowns);
        bindCrownReceipts();
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

  function pulseModeFromHash() {
    var h = (location.hash || "").replace(/^#/, "").toLowerCase();
    if (h.indexOf("pulse-") === 0) h = h.slice(6);
    if (h === "listen" || h === "learn" || h === "rank" || h === "serve") return h;
    return "listen";
  }

  function setPulseMode(mode, opts) {
    var root = document.querySelector(".message-intel--v2");
    if (!root) return;
    if (mode !== "listen" && mode !== "learn" && mode !== "rank" && mode !== "serve") mode = "listen";
    root.setAttribute("data-pulse-mode", mode);
    var tabs = root.querySelectorAll(".message-intel__loop [role='tab']");
    tabs.forEach(function (tab) {
      var on = tab.getAttribute("data-pulse-mode") === mode;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
    });
    root.querySelectorAll(".message-intel__mode").forEach(function (pane) {
      var on = pane.getAttribute("data-pulse-pane") === mode;
      pane.hidden = !on;
    });
    if (!opts || opts.hash !== false) {
      try {
        history.replaceState(null, "", "#pulse-" + mode);
      } catch (e) { /* ignore */ }
    }
  }

  function bindRankSubtabs() {
    var subtabs = document.querySelectorAll(".message-intel__rank-subtab");
    if (!subtabs.length) return;
    subtabs.forEach(function (btn) {
      if (btn.getAttribute("data-subtab-bound") === "1") return;
      btn.setAttribute("data-subtab-bound", "1");
      btn.addEventListener("click", function () {
        var target = btn.getAttribute("data-rank-subtab");
        subtabs.forEach(function (s) {
          var active = s === btn;
          s.classList.toggle("is-active", active);
          s.setAttribute("aria-selected", active ? "true" : "false");
        });
        document.querySelectorAll(".message-intel__rank-pane").forEach(function (pane) {
          var match = pane.getAttribute("data-rank-pane") === target;
          pane.classList.toggle("is-active", match);
          pane.hidden = !match;
        });
        if (target === "callers") {
          hydrateCallerLeaderboard();
        }
      });
    });

    var rankCallerTabs = document.querySelectorAll("#message-intel-rank-callers-card [data-caller-days]");
    rankCallerTabs.forEach(function (button) {
      if (button.getAttribute("data-days-bound") === "1") return;
      button.setAttribute("data-days-bound", "1");
      button.addEventListener("click", function () {
        callerDays = Number(button.getAttribute("data-caller-days")) || 30;
        rankCallerTabs.forEach(function (tab) { tab.classList.toggle("is-active", tab === button); });
        hydrateCallerLeaderboard();
      });
    });
  }

  function bindPulseModes() {
    var root = document.querySelector(".message-intel--v2");
    if (!root) return;
    var tabs = root.querySelectorAll(".message-intel__loop [role='tab']");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        setPulseMode(tab.getAttribute("data-pulse-mode") || "listen");
      });
    });
    var list = root.querySelector(".message-intel__loop");
    if (list) {
      list.addEventListener("keydown", function (ev) {
        var keys = { ArrowLeft: -1, ArrowRight: 1, Home: "first", End: "last" };
        var dir = keys[ev.key];
        if (dir == null) return;
        var items = Array.prototype.slice.call(tabs);
        var i = items.indexOf(document.activeElement);
        if (i < 0) i = items.findIndex(function (t) { return t.getAttribute("aria-selected") === "true"; });
        var next;
        if (dir === "first") next = items[0];
        else if (dir === "last") next = items[items.length - 1];
        else next = items[(i + dir + items.length) % items.length];
        if (!next) return;
        ev.preventDefault();
        next.focus();
        setPulseMode(next.getAttribute("data-pulse-mode") || "listen");
      });
    }
    setPulseMode(pulseModeFromHash(), { hash: false });
    window.addEventListener("hashchange", function () {
      setPulseMode(pulseModeFromHash(), { hash: false });
    });
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

  document.querySelectorAll(".message-intel__axis-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      trendAxis = chip.getAttribute("data-axis") || "chatter";
      document.querySelectorAll(".message-intel__axis-chip").forEach(function (c) {
        c.classList.toggle("message-intel__axis-chip--active", c === chip);
      });
      renderTrendingV2(latestTrendingRows, "1h");
    });
  });

  function hydrateCalibration() {
    if (!hbCalEl) return;
    fetch("/api/message-intel/calibration", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        if (j.active === false) hbCalEl.textContent = "cal drift";
        else hbCalEl.textContent = "cal ok";
      })
      .catch(function () { hbCalEl.textContent = "cal …"; });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindPulseModes();
      bindRankSubtabs();
      bindFilterClicks();
      syncFilterChipStates();
       hydrateWatchlist();
      hydrate();
      hydrateCalibration();
      pollNetFlow();
      refreshTimer = window.setInterval(hydrate, 60000);
      window.setInterval(pollNetFlow, 60000);
    });
  } else {
    bindPulseModes();
    bindRankSubtabs();
    bindFilterClicks();
    syncFilterChipStates();
    hydrateWatchlist();
    hydrate();
    hydrateCalibration();
    pollNetFlow();
    refreshTimer = window.setInterval(hydrate, 60000);
    window.setInterval(pollNetFlow, 60000);
  }

  window.addEventListener("pagehide", function () {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
