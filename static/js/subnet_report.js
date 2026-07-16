/** O3 — subnet report UI (GET /api/report/{netuid}, XSS-safe markdown subset) */
(function () {
  "use strict";

  var panel = document.getElementById("subnet-report-panel");
  var body = document.getElementById("subnet-report-body");
  var titleEl = document.getElementById("subnet-report-title");
  var metaEl = document.getElementById("subnet-report-meta");
  var closeBtn = document.getElementById("subnet-report-close");
  if (!panel || !body) return;

  var openNetuid = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function inline(s) {
    var t = esc(s);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/_([^_]+)_/g, "<em>$1</em>");
    return t;
  }

  function renderMarkdown(md) {
    var lines = String(md || "").split("\n");
    var out = [];
    var inList = false;
    function closeList() {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
    }
    lines.forEach(function (line) {
      if (/^#\s+/.test(line)) {
        closeList();
        out.push('<h2 class="subnet-report__h2">' + inline(line.replace(/^#\s+/, "")) + "</h2>");
      } else if (/^##\s+/.test(line)) {
        closeList();
        out.push('<h3 class="subnet-report__h3">' + inline(line.replace(/^##\s+/, "")) + "</h3>");
      } else if (/^-\s+/.test(line)) {
        if (!inList) {
          out.push('<ul class="subnet-report__list">');
          inList = true;
        }
        out.push("<li>" + inline(line.replace(/^-\s+/, "")) + "</li>");
      } else if (/^_\s*.+_\s*$/.test(line.trim())) {
        closeList();
        out.push(
          '<p class="subnet-report__note">' +
            inline(line.trim().replace(/^_|_$/g, "")) +
            "</p>"
        );
      } else if (!line.trim()) {
        closeList();
      } else {
        closeList();
        out.push('<p class="subnet-report__p">' + inline(line) + "</p>");
      }
    });
    closeList();
    return out.join("");
  }

  function setBusy(on) {
    panel.setAttribute("aria-busy", on ? "true" : "false");
  }

  function setLoading(netuid) {
    openNetuid = netuid;
    panel.hidden = false;
    setBusy(true);
    if (titleEl) titleEl.textContent = "Subnet SN" + netuid;
    if (metaEl) metaEl.textContent = "Loading report…";
    body.innerHTML =
      '<p class="subnet-report__empty" role="status">Fetching /api/report/' +
      esc(netuid) +
      "…</p>";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    panel.focus();
  }

  function renderError(netuid, kind, detail) {
    setBusy(false);
    if (metaEl) metaEl.textContent = kind === "http" ? "HTTP error" : "unavailable";
    var msg =
      kind === "http"
        ? "Report request failed (SN" + esc(netuid) + ") — " + esc(detail || "not found") + "."
        : "Could not load report — network or API unreachable.";
    body.innerHTML = '<p class="subnet-report__empty" role="alert">' + msg + "</p>";
  }

  function renderDriverSummary(d) {
    if (!d || d.status === "error") return "";
    var dec = d.decomposition || {};
    var html =
      '<div class="subnet-report__driver driver-card__inner">' +
      "<h3 class=\"subnet-report__h3\">Market drivers</h3>" +
      "<p class=\"driver-card__headline\">" +
      esc(d.headline || "") +
      "</p>";
    (d.why || []).slice(0, 3).forEach(function (line) {
      html += '<p class="driver-card__why">' + esc(line) + "</p>";
    });
    if (dec.yield_trap) {
      html += '<p class="driver-card__warn">Yield trap flagged at pick time</p>';
    }
    html += "</div>";
    return html;
  }

  function renderPayload(payload) {
    setBusy(false);
    var netuid = payload.netuid;
    var name = payload.name || "SN" + netuid;
    if (titleEl) titleEl.textContent = name + " (SN" + netuid + ")";
    var meta = [];
    if (payload.source) meta.push("source: " + payload.source);
    if (payload.status) meta.push("status: " + payload.status);
    if (metaEl) metaEl.textContent = meta.join(" · ") || "Per-subnet analysis";
    if (payload.status === "error") {
      body.innerHTML =
        '<p class="subnet-report__empty" role="alert">' +
        esc(payload.error || "Report generation failed.") +
        "</p>";
      return;
    }
    var driverHtml = "";
    var sections = payload.sections || {};
    if (sections.market_drivers) {
      driverHtml = renderDriverSummary(sections.market_drivers);
    }
    if (payload.markdown) {
      body.innerHTML =
        driverHtml +
        '<article class="subnet-report__digest">' +
        renderMarkdown(payload.markdown) +
        "</article>";
    } else if (payload.message) {
      body.innerHTML = '<p class="subnet-report__empty">' + esc(payload.message) + "</p>";
    } else {
      body.innerHTML = '<p class="subnet-report__empty">No report content for this subnet.</p>';
    }
  }

  function show(netuid) {
    var id = parseInt(String(netuid), 10);
    if (!id && id !== 0) return;
    setLoading(id);
    fetch("/api/report/" + id)
      .then(function (r) {
        if (!r.ok) {
          renderError(id, "http", "HTTP " + r.status);
          return null;
        }
        return r.json();
      })
      .then(function (payload) {
        if (payload) renderPayload(payload);
      })
      .catch(function () {
        renderError(id, "network");
      });
  }

  function hide() {
    panel.hidden = true;
    openNetuid = null;
    setBusy(false);
  }

  document.addEventListener("subnet:report", function (e) {
    var netuid = e.detail && e.detail.netuid;
    if (netuid != null) show(netuid);
  });

  if (closeBtn) closeBtn.addEventListener("click", hide);

  document.addEventListener("keydown", function (e) {
    if (panel.hidden || openNetuid == null) return;
    if (e.key === "Escape") {
      e.preventDefault();
      hide();
    }
  });

  window.SubnetReport = { show: show, hide: hide };
})();
