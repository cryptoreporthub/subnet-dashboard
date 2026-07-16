/** §19.M1 — live message-intel feed UI (GET /api/message-intel) */
(function () {
  "use strict";

  var feed = document.getElementById("message-intel-feed");
  var meta = document.getElementById("message-intel-meta");
  var sub = document.getElementById("message-intel-sub");
  if (!feed) return;

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

  function renderEmpty(listener) {
    listener = listener || {};
    if (listener.live) {
      return (
        '<p class="empty">Listener live — monitoring group traffic. ' +
        "Messages appear here as they are ingested.</p>"
      );
    }
    if (listener.reason === "disabled") {
      return '<p class="empty">Message-intel listener is off on this deploy.</p>';
    }
    if (listener.reason === "missing_telegram_creds") {
      return '<p class="empty">Telegram creds not configured — ingest via API only.</p>';
    }
    return '<p class="empty">No messages ingested yet.</p>';
  }

  function applyMeta(payload, status) {
    var listener = (status && status.listener) || (payload.meta && payload.meta.listener) || {};
    var total =
      (status && status.store && status.store.total_messages) ||
      (payload.meta && payload.meta.total_messages) ||
      0;
    if (meta) {
      var parts = [];
      if (listener.live) parts.push("listener live");
      else if (listener.reason) parts.push(listener.reason);
      parts.push(total + " stored");
      meta.textContent = parts.join(" · ");
    }
    if (sub && listener.live) {
      sub.textContent = "Live ingest from Telegram — newest messages first.";
    }
  }

  async function hydrate() {
    try {
      var statusRes = await fetch("/api/message-intel/status");
      var status = statusRes.ok ? await statusRes.json() : null;
      var listRes = await fetch("/api/message-intel?limit=20");
      if (!listRes.ok) throw new Error("HTTP " + listRes.status);
      var payload = await listRes.json();
      applyMeta(payload, status);
      if (payload.empty) {
        feed.innerHTML = renderEmpty(status && status.listener);
      } else {
        feed.innerHTML = renderMessages(payload.messages);
      }
    } catch (e) {
      if (meta) meta.textContent = "unavailable";
      feed.innerHTML =
        '<p class="empty">Could not load message intel — try again shortly.</p>';
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrate);
  } else {
    hydrate();
  }
})();
