/**
 * H1 — Hour watch Now rib + shift whisper (cockpit.picks consumer).
 */
(function () {
  "use strict";

  var whisperTimer = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtAge(iso) {
    if (!iso) return "";
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
    if (mins < 1) return "just now";
    if (mins === 1) return "1m ago";
    return mins + "m ago";
  }

  function dayHold(snapshot) {
    var day = snapshot && snapshot.day;
    if (!day) return false;
    return String(day.action || "HOLD").toUpperCase() === "HOLD" && !day.published;
  }

  function renderShiftWhisper(meta) {
    var el = document.getElementById("hour-watch-shift");
    if (!el) return;
    if (!meta || !meta.changed || !meta.previous_lead) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    var prev = meta.previous_lead;
    var lead = document.getElementById("hour-watch-now");
    var curName = lead && lead.dataset.name ? lead.dataset.name : "lead";
    el.textContent = "1h lead shifted · " + (prev.name || "SN" + prev.netuid) + " → " + curName;
    el.hidden = false;
    if (whisperTimer) clearTimeout(whisperTimer);
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduced) {
      whisperTimer = setTimeout(function () {
        el.hidden = true;
      }, 8000);
    }
  }

  function patchHourWatch(snapshot) {
    var host = document.getElementById("hour-watch-now");
    if (!host || !snapshot) return;

    var hour = snapshot.hour || {};
    var picks = hour.picks || [];
    var meta = hour.meta || {};
    var emittedAt = snapshot.emitted_at;

    if (!picks.length) {
      host.className = "hour-watch-now hour-watch-now--quiet";
      host.textContent = meta.quiet_reason || "Council quiet on 1h — no name cleared the short lens";
      host.removeAttribute("href");
      host.dataset.netuid = "";
      host.dataset.name = "";
      renderShiftWhisper(meta);
      return;
    }

    var lead = picks[0];
    var pct = Math.round(Number(lead.final_confidence || lead.confidence || 0) * 100);
    var name = lead.name || (lead.netuid != null ? "SN" + lead.netuid : "—");
    var age = fmtAge(lead.generated_at || emittedAt);
    var line = "Now · " + name;
    if (lead.netuid != null) line += " SN" + lead.netuid;
    line += " · " + pct + "% · exploratory";
    if (age) line += " · updated " + age;
    if (dayHold(snapshot)) line += " · not today's call";

    host.className = "hour-watch-now hour-watch-now--live";
    host.textContent = line;
    host.href = "/?focus=" + encodeURIComponent(String(lead.netuid));
    host.dataset.netuid = String(lead.netuid);
    host.dataset.name = name;
    renderShiftWhisper(meta);
  }

  window.HourWatchUI = {
    patchHourWatch: patchHourWatch,
  };
})();
