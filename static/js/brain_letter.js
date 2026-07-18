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

  function renderToday(pick) {
    pick = pick || {};
    if (!pick.name && !pick.why) {
      return '<p class="weekly-letter__note">Council on HOLD — waiting for audit gate.</p>';
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
    if (pick.judge_citations && pick.judge_citations.length) {
      html += '<ul class="weekly-letter__list">';
      pick.judge_citations.forEach(function (c) {
        html += "<li>" + esc(c.label || c.source) + ": score " + esc(c.score) + "</li>";
      });
      html += "</ul>";
    }

    var card = pick.driver_card || {};
    if (card.status === "success") {
      var dec = card.decomposition || {};
      if (dec.staking_yield_apy != null) {
        html +=
          '<p class="weekly-letter__note">Staking APY ' +
          Number(dec.staking_yield_apy).toFixed(1) +
          "% <span class=\"driver-card__hint\">(income — not price)</span></p>";
      }
      if (dec.price_change_7d != null) {
        html +=
          '<p class="weekly-letter__note">Token price 7d: ' +
          Number(dec.price_change_7d).toFixed(1) +
          "%</p>";
      }
      if (dec.yield_trap) {
        html += '<p class="weekly-letter__warn">Yield trap — high APY but token falling</p>';
      }
      (card.why || []).slice(0, 2).forEach(function (line) {
        html += '<p class="weekly-letter__note">' + esc(line) + "</p>";
      });
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

  function renderStory(story) {
    story = story || {};
    var steps = story.steps || [];
    if (!steps.length) {
      return '<p class="weekly-letter__note">Story path appears when council clears a call.</p>';
    }
    var html = '<ol class="brain-letter__steps">';
    steps.forEach(function (step) {
      html +=
        '<li class="brain-letter__step brain-letter__step--' +
        esc(step.status || "done") +
        '"><span class="brain-letter__step-label">' +
        esc(step.label || "") +
        "</span> " +
        esc(step.title || "") +
        "</li>";
    });
    html += "</ol>";
    return html;
  }

  function render(root, payload) {
    if (!root) return;
    if (!payload || payload.status !== "ok") {
      root.innerHTML = '<p class="weekly-letter__empty">Brain letter unavailable right now.</p>';
      return;
    }
    root.innerHTML =
      '<article class="weekly-letter__digest brain-letter__digest">' +
      block("Today we watch", "brain-letter-today", renderToday(payload.pick)) +
      block(
        "What the brain learned",
        "brain-letter-learned",
        renderLearned(payload.trust_banner, payload.working)
      ) +
      block(
        "Integrity",
        "brain-letter-integrity",
        renderIntegrity(payload.trust_banner, payload.brain_ui_ready, payload.watchdog)
      ) +
      block("How we got here", "brain-letter-story", renderStory(payload.story_path)) +
      "</article>";
  }

  async function hydrate() {
    var root = $("brain-letter-root");
    var dateEl = $("brain-letter-date");
    if (!root) return;
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    };
    try {
      var payload = await fetchJson("/api/letter/brain", 15000);
      if (dateEl && payload.date) {
        dateEl.textContent = "Today " + payload.date + " (UTC) · living narrative";
      }
      render(root, payload);
      if (window.LetterExport && window.LetterExport.brain) {
        window.LetterExport.brain.setMarkdown(
          payload.markdown,
          "brain-letter-" + (payload.date || "export")
        );
      }
    } catch (e) {
      if (dateEl) dateEl.textContent = "Today's narrative";
      root.innerHTML =
        '<p class="weekly-letter__empty">Could not load brain letter — try again shortly.</p>';
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
