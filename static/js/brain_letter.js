/** §21 L11 — Brain letter UI (RF-2: trust_banner accuracy only) */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function block(title, id, body) {
    return (
      '<section class="weekly-letter__block" aria-labelledby="' +
      id +
      '">' +
      '<h3 class="weekly-letter__block-title" id="' +
      id +
      '">' +
      esc(title) +
      "</h3>" +
      body +
      "</section>"
    );
  }

  function holdCopy() {
    return "Council on HOLD — confidence hasn't cleared a sized long.";
  }

  function renderToday(pick) {
    pick = pick || {};
    if (!pick.name && !pick.why) {
      return '<p class="weekly-letter__note">' + esc(holdCopy()) + "</p>";
    }
    var act = String(pick.action || "HOLD").toUpperCase();
    if (act === "LONG") act = "BUY";
    var html = "";
    if (pick.published && pick.name) {
      html +=
        '<p class="weekly-letter__lead"><strong>' +
        esc(act) +
        " " +
        esc(pick.name) +
        (pick.netuid != null ? " (SN" + esc(pick.netuid) + ")" : "") +
        "</strong></p>";
    } else if (pick.name) {
      html +=
        '<p class="weekly-letter__lead">Candidate: <strong>' +
        esc(pick.name) +
        "</strong> · no audited long yet</p>";
    }
    if (pick.why) html += '<p class="weekly-letter__note">' + esc(pick.why) + "</p>";
    if (pick.dissent) {
      html += '<p class="weekly-letter__note"><strong>Council split:</strong> ' + esc(pick.dissent) + "</p>";
    }
    return html;
  }

  function renderLearned(tb, working) {
    tb = tb || {};
    working = working || {};
    var html = "";
    if (tb.ready && tb.headline) {
      html += '<p class="weekly-letter__lead">' + esc(tb.headline) + "</p>";
    } else if (tb.message) {
      html += '<p class="weekly-letter__note">' + esc(tb.message) + "</p>";
    } else {
      html += '<p class="weekly-letter__note">Not enough graded picks to quote accuracy yet.</p>';
    }

    var signals = working.top_price_signals || [];
    if (signals.length) {
      html += '<ul class="weekly-letter__list">';
      signals.slice(0, 3).forEach(function (row) {
        var pct = row.hit_rate != null ? Math.round(row.hit_rate * 100) : "—";
        html +=
          '<li class="weekly-letter__item"><span class="weekly-letter__item-name">' +
          esc(row.signal || row.tag || "signal") +
          "</span><span class=\"weekly-letter__item-meta\">" +
          pct +
          "% hit · n=" +
          esc(row.n) +
          "</span></li>";
      });
      html += "</ul>";
    } else {
      html +=
        '<p class="weekly-letter__note">Signal rankings fill in as more picks grade on token price.</p>';
    }
    if (working.disclaimer) {
      html += '<p class="weekly-letter__note weekly-letter__disclaimer">' + esc(working.disclaimer) + "</p>";
    }
    return html;
  }

  function renderOutlook(outlook) {
    return '<p class="weekly-letter__lead">' + esc(outlook || "No sized call this window — watching the desk into resolve.") + "</p>";
  }

  function renderIntegrity(tb, ready, watchdog) {
    tb = tb || {};
    watchdog = watchdog || {};
    var html = "";
    if (watchdog.warning) {
      html +=
        '<p class="weekly-letter__warn">' +
        esc(watchdog.reason || "Resolver watchdog warning") +
        "</p>";
    }
    if (tb.expired != null && tb.expired_rate != null) {
      html +=
        '<p class="weekly-letter__note">Expired backlog: ' +
        esc(tb.expired) +
        " (" +
        Math.round(Number(tb.expired_rate) * 100) +
        "% of ledger)</p>";
    }
    html +=
      '<p class="weekly-letter__note">Trust surfaces: <strong>' +
      (ready ? "ready" : "blocked") +
      "</strong></p>";
    return html;
  }

  function render(root, payload) {
    if (!root) return;
    if (!payload || payload.status !== "ok") {
      if (!root.querySelector(".weekly-letter__digest") && !root.querySelector(".weekly-letter__empty")) {
        root.innerHTML = '<p class="weekly-letter__empty">Brief writes after the first graded windows land.</p>';
      }
      return;
    }
    root.innerHTML =
      '<article class="weekly-letter__digest brain-letter__digest">' +
      block("What changed since yesterday", "brain-letter-learned", renderLearned(payload.trust_banner, payload.working)) +
      block("Today", "brain-letter-today", renderToday(payload.pick)) +
      block("Next", "brain-letter-next", renderOutlook(payload.outlook)) +
      block(
        "Integrity",
        "brain-letter-integrity",
        renderIntegrity(payload.trust_banner, payload.brain_ui_ready, payload.watchdog)
      ) +
      "</article>";
    var section = document.getElementById("section-brain-letter");
    if (section) section.setAttribute("data-brain-state", payload.empty ? "quiet" : "live");
  }

  async function hydrate() {
    var root = $("brain-letter-root");
    var dateEl = $("brain-letter-date");
    var section = $("section-brain-letter");
    if (!root) return;
    var hadSsr = section && section.getAttribute("data-ssr") === "1";
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    };
    try {
      var payload = await fetchJson("/api/letter/brain", 15000);
      if (dateEl) {
        dateEl.textContent = "Morning brief · graded memory" + (payload.date ? " · " + payload.date : "");
      }
      render(root, payload);
      if (section) section.setAttribute("data-ssr", "1");
      if (window.LetterExport && window.LetterExport.brain) {
        window.LetterExport.brain.setMarkdown(
          payload.markdown,
          "brain-letter-" + (payload.date || "export")
        );
      }
    } catch (e) {
      if (dateEl && !hadSsr) dateEl.textContent = "Morning brief · graded memory";
      if (!hadSsr && !root.querySelector(".weekly-letter__digest")) {
        root.innerHTML =
          '<p class="weekly-letter__empty">Brief writes after the first graded windows land.</p>';
      }
      if (section) section.setAttribute("data-brain-state", "quiet");
      if (window.LetterExport && window.LetterExport.brain) {
        window.LetterExport.brain.setMarkdown("");
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrate);
  } else {
    hydrate();
  }

  document.addEventListener("home-daily-call-updated", hydrate);
})();
