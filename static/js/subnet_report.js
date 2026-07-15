/** O3 — subnet report UI (GET /api/report/{netuid}, XSS-safe markdown subset) */
(function () {
  "use strict";

  var panel = document.getElementById("subnet-report-panel");
  var body = document.getElementById("subnet-report-body");
  var titleEl = document.getElementById("subnet-report-title");
  var metaEl = document.getElementById("subnet-report-meta");
  var closeBtn = document.getElementById("subnet-report-close");
  if (!panel || !body) return;

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

  function setLoading(netuid) {
    panel.hidden = false;
    if (titleEl) titleEl.textContent = "Subnet SN" + netuid;
    if (metaEl) metaEl.textContent = "Loading report…";
    body.innerHTML = '<p class="subnet-report__empty">Fetching /api/report/' + esc(netuid) + "…</p>";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderPayload(payload) {
    var netuid = payload.netuid;
    var name = payload.name || "SN" + netuid;
    if (titleEl) titleEl.textContent = name + " (SN" + netuid + ")";
    var meta = [];
    if (payload.source) meta.push("source: " + payload.source);
    if (payload.status) meta.push("status: " + payload.status);
    if (metaEl) metaEl.textContent = meta.join(" · ") || "Per-subnet analysis";
    if (payload.markdown) {
      body.innerHTML = '<article class="subnet-report__digest">' + renderMarkdown(payload.markdown) + "</article>";
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
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(renderPayload)
      .catch(function () {
        if (metaEl) metaEl.textContent = "unavailable";
        body.innerHTML =
          '<p class="subnet-report__empty">Could not load report — API unreachable or SN' +
          esc(id) +
          " missing.</p>";
      });
  }

  function hide() {
    panel.hidden = true;
  }

  document.addEventListener("subnet:report", function (e) {
    var netuid = e.detail && e.detail.netuid;
    if (netuid != null) show(netuid);
  });

  if (closeBtn) closeBtn.addEventListener("click", hide);

  window.SubnetReport = { show: show, hide: hide };
})();
