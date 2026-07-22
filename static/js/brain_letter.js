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

  function gradedCountFromDom() {
    var el = document.getElementById("kpi-graded");
    if (!el) return 0;
    var m = String(el.textContent || "").match(/n=(\d+)/);
    return m ? parseInt(m[1], 10) : 0;
  }

  function hasSsrDigest(root, section) {
    if (root && root.querySelector(".weekly-letter__digest")) return true;
    if (section && section.getAttribute("data-ssr") === "1") return true;
    return gradedCountFromDom() > 0;
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
    } else if (gradedCountFromDom() > 0) {
      html += '<p class="weekly-letter__note">Graded memory is on disk — letter refresh will catch up.</p>';
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
          '</span><span class="weekly-letter__item-meta">' +
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


  function renderYesterday(outcome) {
    if (!outcome) return "";
    return block(
      "Yesterday",
      "brain-letter-yesterday",
      '<p class="weekly-letter__lead">' + esc(outcome) + "</p>"
    );
  }

  function renderSeedStrip(rows) {
    rows = rows || [];
    if (!rows.length) return "";
    var html = '<ul class="weekly-letter__list">';
    rows.slice(0, 5).forEach(function (row) {
      html +=
        '<li class="weekly-letter__item"><span class="weekly-letter__item-name">' +
        esc(row.name || "SN" + row.netuid) +
        '</span><span class="weekly-letter__item-meta">SN' +
        esc(row.netuid) +
        " · " +
        esc(row.note || "verify on desk") +
        "</span></li>";
    });
    html += "</ul>";
    return block("New subnets on the desk", "brain-letter-seeds", html);
  }

  function bindDeskCopy(deskBlock) {
    var btn = $("brain-letter-copy-desk");
    if (!btn) return;
    var text = deskBlock || "";
    btn.disabled = !text;
    btn.onclick = function () {
      if (!text || !navigator.clipboard) return;
      navigator.clipboard.writeText(text).catch(function () {});
    };
  }

  function renderOutlook(outlook) {
    var text = outlook || "No sized call this window — watching the desk into resolve.";
    if (/over the next\s+0m/i.test(text)) {
      text = "Resolve window not set — flat until the pick locks.";
    }
    return '<p class="weekly-letter__lead">' + esc(text) + "</p>";
  }

    var text = outlook || "No sized call this window — watching the desk into resolve.";
    if (/over the next\s+0m/i.test(text)) {
      text = "Resolve window not set — flat until the pick locks.";
    }
    return '<p class="weekly-letter__lead">' + esc(text) + "</p>";
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
      if (!hasSsrDigest(root, document.getElementById("section-brain-letter"))) {
        var graded = gradedCountFromDom();
        root.innerHTML =
          graded > 0
            ? '<p class="weekly-letter__empty">Letter refresh delayed — ' +
              graded +
              " picks graded on disk; retrying API.</p>"
            : '<p class="weekly-letter__empty">Brief writes after the first graded windows land.</p>';
      }
      return;
    }
    root.innerHTML =
      '<article class="weekly-letter__digest brain-letter__digest">' +
      renderYesterday(payload.yesterday_outcome) +
      renderSeedStrip(payload.seed_strip) +
      block("What changed since yesterday", "brain-letter-learned", renderLearned(payload.trust_banner, payload.working)) +
      block("Today", "brain-letter-today", renderToday(payload.pick)) +
      block("Next", "brain-letter-next", renderOutlook(payload.outlook)) +
      block(
        "Integrity",
        "brain-letter-integrity",
        renderIntegrity(payload.trust_banner, payload.brain_ui_ready, payload.watchdog)
      ) +
      "</article>";
    bindDeskCopy(payload.desk_block);
    var section = document.getElementById("section-brain-letter");
    if (section) section.setAttribute("data-brain-state", payload.empty ? "quiet" : "live");
  }

  async function hydrate(payload) {
    var root = $("brain-letter-root");
    var dateEl = $("brain-letter-date");
    var section = $("section-brain-letter");
    if (!root) return;
    var hadSsr = hasSsrDigest(root, section);
    try {
      var data = payload;
      if (!data) {
        if (window.apiFetchJsonRetry) {
          data = await window.apiFetchJsonRetry("/api/letter/brain", 25000, 2);
        } else if (window.apiFetchJson) {
          data = await window.apiFetchJson("/api/letter/brain", 25000);
        } else {
          var r = await fetch("/api/letter/brain", { headers: { Accept: "application/json" } });
          if (!r.ok) throw new Error("HTTP " + r.status);
          data = await r.json();
        }
      }
      if (dateEl) {
        dateEl.textContent = "Morning brief · graded memory" + (data.date ? " · " + data.date : "");
      }
      render(root, data);
      bindDeskCopy(data.desk_block);
      if (section) section.setAttribute("data-ssr", "1");
      if (window.LetterExport && window.LetterExport.brain) {
        window.LetterExport.brain.setMarkdown(
          data.markdown,
          "brain-letter-" + (data.date || "export")
        );
      }
    } catch (e) {
      if (dateEl && !hadSsr) dateEl.textContent = "Morning brief · graded memory";
      if (!hasSsrDigest(root, section)) {
        var graded = gradedCountFromDom();
        root.innerHTML =
          graded > 0
            ? '<p class="weekly-letter__empty">Letter refresh delayed — ' +
              graded +
              " picks graded on disk; retrying API.</p>"
            : '<p class="weekly-letter__empty">Brief writes after the first graded windows land.</p>';
      }
      if (section) section.setAttribute("data-brain-state", hadSsr ? "live" : "quiet");
      if (window.LetterExport && window.LetterExport.brain && !hadSsr) {
        window.LetterExport.brain.setMarkdown("");
      }
    }
  }

  window.BrainLetter = { hydrate: hydrate, render: render };

  if (document.documentElement.dataset.hydrate !== "1") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { hydrate(); });
    } else {
      hydrate();
    }
    document.addEventListener("home-daily-call-updated", hydrate);
  }
})();
