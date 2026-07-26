/** §19.M1 — Telegram message-intel UI (trending, champions, live feed) */
(function () {
  "use strict";

  var feed = document.getElementById("message-intel-feed");
  var meta = document.getElementById("message-intel-meta");
  var sub = document.getElementById("message-intel-sub");
  var trendingEl = document.getElementById("message-intel-trending");
  var championsEl = document.getElementById("message-intel-champions");
  var refreshBtn = document.getElementById("message-intel-trending-refresh");
  if (!feed) return;

  var lastStatus = null;
  var refreshTimer = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function snippet(text, n) {
    var t = String(text || "").trim();
    if (t.length <= n) return t;
    return t.slice(0, n) + "…";
  }

  function sentimentLabel(analysis) {
    if (!analysis || typeof analysis !== "object") return "—";
    var s = String(analysis.sentiment || "").toLowerCase();
    if (s === "bullish" || s === "positive") return "bullish";
    if (s === "bearish" || s === "negative") return "bearish";
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
    var reason = String(listener.reason || "");
    return (
      reason === "idle_not_started" ||
      reason === "worker_heavy_off" ||
      reason === "disabled" ||
      reason === "missing_telegram_creds"
    );
  }

  function renderTrending(rows, listener) {
    if (listenerIdle(listener)) {
      return (
        '<p class="empty">Telegram listener is not running yet — trending fills once messages are ingested.</p>'
      );
    }
    if (!rows || !rows.length) {
      return '<p class="empty">No subnet chatter in the last hour. Check back after the group warms up.</p>';
    }
    var html = '<ul class="message-intel__trend-list">';
    rows.forEach(function (row, idx) {
      var rank = idx + 1;
      html +=
        '<li class="message-intel__trend-item">' +
        '<span class="message-intel__rank ' +
        rankClass(rank) +
        '">#' +
        rank +
        "</span>" +
        '<div class="message-intel__trend-main">' +
        '<a class="message-intel__trend-name" href="/subnet/' +
        esc(row.netuid) +
        '">' +
        esc(row.name) +
        ' <b>SN' +
        esc(row.netuid) +
        "</b></a>" +
        '<span class="badge ' +
        sentimentBadgeClass(row.sentiment) +
        '">' +
        esc(row.sentiment || "Cautious") +
        "</span>" +
        "</div>" +
        '<div class="message-intel__trend-stats">' +
        '<span class="message-intel__mentions">' +
        esc(row.mentions) +
        " mentions</span>" +
        (row.avg_conviction
          ? '<span class="message-intel__conv">conv ' + esc(row.avg_conviction) + "</span>"
          : "") +
        changeLabel(row.change_1h) +
        sparklineSvg(row.sparkline) +
        "</div></li>";
    });
    html += "</ul>";
    return html;
  }

  function renderChampions(rows, authorsUnavailable) {
    if (authorsUnavailable) {
      return '<p class="empty">Weekly champions API unavailable — redeploy to pick up the latest build.</p>';
    }
    if (!rows || !rows.length) {
      return '<p class="empty">No contributor history yet — champions appear after a week of Telegram traffic.</p>';
    }
    var html = '<ul class="message-intel__champ-list">';
    rows.forEach(function (row, idx) {
      var rank = idx + 1;
      var handle = row.author_username ? "@" + String(row.author_username).replace(/^@/, "") : "";
      var rx = row.reactions || {};
      html +=
        '<li class="message-intel__champ-item">' +
        '<span class="message-intel__rank ' +
        rankClass(rank) +
        '">#' +
        rank +
        "</span>" +
        '<span class="message-intel__avatar" aria-hidden="true">' +
        esc(row.initials || "?") +
        "</span>" +
        '<div class="message-intel__champ-main">' +
        '<span class="message-intel__champ-name">' +
        esc(row.author_name || "Unknown") +
        "</span>" +
        (handle ? '<span class="message-intel__champ-handle">' + esc(handle) + "</span>" : "") +
        '<span class="message-intel__influence">' +
        esc(row.influence_score) +
        " influence</span>" +
        (row.hit_rate != null && row.graded
          ? '<span class="message-intel__hit">' +
            esc(row.hit_rate) +
            "% hit · n=" +
            esc(row.graded) +
            "</span>"
          : "") +
        "</div>" +
        '<div class="message-intel__champ-meta">' +
        '<span>' +
        esc(row.message_count) +
        " msgs</span>" +
        '<span>' +
        esc(row.subnet_count) +
        " subnets</span>" +
        '<span class="message-intel__emoji">' +
        (rx.fire ? "🔥" + rx.fire + " " : "") +
        (rx.heart ? "❤️" + rx.heart + " " : "") +
        (rx.thumbs ? "👍" + rx.thumbs : "") +
        "</span></div></li>";
    });
    html += "</ul>";
    return html;
  }

  function renderMessages(rows) {
    if (!rows || !rows.length) return "";
    var html = '<ul class="message-intel__list">';
    rows.forEach(function (row) {
      var label = sentimentLabel(row.analysis);
      var badge =
        label === "bullish" ? "badge-buy" : label === "bearish" ? "badge-sell" : "badge-watch";
      html +=
        '<li class="message-intel__item">' +
        '<div class="message-intel__item-head">' +
        '<span class="message-intel__author">' +
        esc(row.author_name || row.author_username || "unknown") +
        "</span>" +
        '<span class="badge ' +
        badge +
        '">' +
        esc(label) +
        "</span>" +
        "</div>" +
        '<p class="message-intel__content">' +
        esc(snippet(row.content, 280)) +
        "</p>" +
        (row.timestamp
          ? '<span class="message-intel__time">' + esc(row.timestamp) + "</span>"
          : "") +
        "</li>";
    });
    html += "</ul>";
    return html;
  }

  function renderFeedEmpty(listener) {
    listener = listener || {};
    if (listener.live) {
      return (
        '<p class="empty">Listener live — monitoring Telegram group traffic. ' +
        "Messages appear here as they are ingested.</p>"
      );
    }
    if (listener.reason === "disabled") {
      return '<p class="empty">Telegram listener is off on this deploy (<code>MESSAGE_INTEL_LISTENER</code>).</p>';
    }
    if (listener.reason === "worker_heavy_off") {
      return '<p class="empty">Listener skipped in essential worker mode — set <code>WORKER_HEAVY=full</code> on Fly.</p>';
    }
    if (listener.reason === "missing_telegram_creds") {
      return '<p class="empty">Telegram creds not configured — ingest via API only.</p>';
    }
    if (listener.reason === "idle_not_started") {
      return '<p class="empty">Listener configured but not started yet — check worker process on Fly.</p>';
    }
    return '<p class="empty">No Telegram messages ingested yet.</p>';
  }

  function applyMeta(payload, status) {
    var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
    var total =
      (status && status.store && status.store.total_messages) ||
      (payload.meta && payload.meta.total_messages) ||
      0;
    if (meta) {
      var parts = ["telegram"];
      if (listener.live) parts.push("listener live");
      else if (listener.reason) parts.push(listener.reason);
      parts.push(total + " stored");
      meta.textContent = parts.join(" · ");
      if (listener.hint && !listener.live) {
        meta.title = listener.hint;
      }
    }
    if (sub) {
      if (listener.live) {
        sub.textContent = "Live ingest from the monitored Telegram group — newest messages first.";
      } else if (listener.hint) {
        sub.textContent = listener.hint;
      } else if (listener.reason === "idle_not_started") {
        sub.textContent = "Credentials present — start the worker listener to begin ingest.";
      }
    }
    lastStatus = status;
  }

  async function hydrate() {
    try {
      var statusRes = await fetch("/api/message-intel/status");
      var status = statusRes.ok ? await statusRes.json() : null;
      var listRes = await fetch("/api/message-intel?limit=20");
      if (!listRes.ok) throw new Error("HTTP " + listRes.status);
      var payload = await listRes.json();
      applyMeta(payload, status);

      var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
      var trending = (payload.meta && payload.meta.trending) || [];
      if (trendingEl) {
        trendingEl.innerHTML = renderTrending(trending, listener);
      }

      var authorsUnavailable = false;
      var authors = [];
      try {
        var authorsRes = await fetch("/api/message-intel/authors?limit=8");
        if (authorsRes.ok) {
          var authorsPayload = await authorsRes.json();
          authors = authorsPayload.authors || [];
        } else if (authorsRes.status === 404) {
          authorsUnavailable = true;
        }
      } catch (e) {
        authorsUnavailable = true;
      }
      if (championsEl) {
        championsEl.innerHTML = renderChampions(authors, authorsUnavailable);
      }

      if (payload.empty) {
        feed.innerHTML = renderFeedEmpty(status && status.listener);
      } else {
        feed.innerHTML = renderMessages(payload.messages);
      }
    } catch (e) {
      if (meta) meta.textContent = "unavailable";
      if (trendingEl) {
        trendingEl.innerHTML = '<p class="empty">Could not load trending.</p>';
      }
      if (championsEl) {
        championsEl.innerHTML = '<p class="empty">Could not load champions.</p>';
      }
      feed.innerHTML =
        '<p class="empty">Could not load Telegram message intel — try again shortly.</p>';
    }
  }

  document.addEventListener("home:cockpit-tick", hydrate);
  if (refreshBtn) {
    refreshBtn.addEventListener("click", hydrate);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      hydrate();
      refreshTimer = window.setInterval(hydrate, 60000);
    });
  } else {
    hydrate();
    refreshTimer = window.setInterval(hydrate, 60000);
  }

  window.addEventListener("pagehide", function () {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
