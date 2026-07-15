/** §17.F1/F2 — home watchlist pin + conviction alert check */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  async function fetchJson(url, opts) {
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  async function loadWatchlist() {
    return fetchJson("/api/watchlist");
  }

  async function saveWatchlist(netuids) {
    return fetchJson("/api/watchlist", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ netuids: netuids }),
    });
  }

  function setStatus(msg) {
    const el = $("home-habit-status");
    if (!el) return;
    let note = el.querySelector(".home-habit-status__note");
    if (!note) {
      note = document.createElement("span");
      note.className = "home-habit-status__note";
      el.appendChild(note);
    }
    note.textContent = msg;
  }

  function updatePinButton(netuid, pinned) {
    const btn = $("habit-pin-btn");
    if (!btn || !netuid) return;
    btn.dataset.pinned = pinned ? "1" : "0";
    btn.textContent = pinned ? "Unpin subnet" : "Pin to watchlist";
  }

  function updateWatchSummary(count) {
    const el = $("habit-watchlist-summary");
    if (el) el.textContent = "Watchlist: " + count + " pinned";
  }

  function initPin() {
    const btn = $("habit-pin-btn");
    if (!btn || btn.disabled) return;
    btn.addEventListener("click", async function () {
      const netuid = parseInt(btn.dataset.netuid || "", 10);
      if (!netuid) return;
      try {
        const wl = await loadWatchlist();
        let pins = (wl.netuids || []).map(Number).filter(Boolean);
        const pinned = btn.dataset.pinned === "1";
        if (pinned) {
          pins = pins.filter(function (n) {
            return n !== netuid;
          });
        } else if (pins.indexOf(netuid) < 0) {
          pins.push(netuid);
        }
        const saved = await saveWatchlist(pins);
        updatePinButton(netuid, !pinned);
        updateWatchSummary((saved.netuids || []).length);
        setStatus(pinned ? "Removed SN" + netuid + " from watchlist" : "Pinned SN" + netuid);
      } catch (e) {
        setStatus("Watchlist update failed");
      }
    });
  }

  function initAlerts() {
    const btn = $("habit-alert-btn");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      if (btn.dataset.enabled !== "1") {
        setStatus("Conviction alerts disabled — enable CONVICTION_ALERTS_ENABLED on deploy");
        return;
      }
      btn.disabled = true;
      try {
        const out = await fetchJson("/api/conviction-alerts/notify", { method: "POST" });
        const created = out.created != null ? out.created : out.alerts_created;
        setStatus(
          "Alert check done" +
            (created != null ? " · " + created + " created" : "") +
            (out.reason ? " · " + out.reason : "")
        );
        const summary = $("habit-alerts-summary");
        if (summary && out.last_run_at) {
          summary.textContent = "Alerts on · last " + out.last_run_at;
        }
      } catch (e) {
        setStatus("Conviction alert check failed");
      } finally {
        btn.disabled = false;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initPin();
      initAlerts();
    });
  } else {
    initPin();
    initAlerts();
  }
})();
