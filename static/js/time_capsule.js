/** §21 L12/L14 — time-capsule replay + shareable graded call card */
(function () {
  "use strict";

  var modal = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function ensureModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "time-capsule-modal";
    modal.className = "time-capsule-modal";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="time-capsule-modal__backdrop" data-close="1"></div>' +
      '<div class="time-capsule-modal__panel" role="dialog" aria-modal="true" aria-labelledby="time-capsule-title">' +
      '<button type="button" class="time-capsule-modal__close" data-close="1" aria-label="Close">×</button>' +
      '<h3 class="time-capsule-modal__title" id="time-capsule-title">Time capsule</h3>' +
      '<div class="time-capsule-modal__body" id="time-capsule-body"></div>' +
      '<div class="time-capsule-modal__actions">' +
      '<button type="button" class="time-capsule-modal__copy" id="time-capsule-copy">Copy graded call</button>' +
      "</div></div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (e) {
      if (e.target.closest("[data-close]")) closeModal();
    });
    return modal;
  }

  function closeModal() {
    if (modal) modal.hidden = true;
  }

  function renderCapsule(payload) {
    ensureModal();
    var body = document.getElementById("time-capsule-body");
    var copyBtn = document.getElementById("time-capsule-copy");
    if (!body) return;
    if (!payload || payload.status !== "success") {
      body.innerHTML = '<p class="time-capsule-modal__empty">Prediction not found.</p>';
      if (copyBtn) copyBtn.hidden = true;
      modal.hidden = false;
      return;
    }
    var cap = payload.capsule || {};
    var snap = cap.subnet_snapshot || {};
    var html = '<p class="time-capsule-modal__stmt">' + esc(cap.statement || "—") + "</p>";
    if (cap.predicted_pct != null && cap.actual_pct != null) {
      html +=
        '<p class="time-capsule-modal__move">Expected ' +
        Number(cap.predicted_pct).toFixed(1) +
        "% → actual " +
        Number(cap.actual_pct).toFixed(1) +
        "% " +
        (cap.correct ? "✓" : "✗") +
        "</p>";
    }
    if (snap.staking_yield_apy != null) {
      html +=
        '<p class="time-capsule-modal__snap">Staking APY ' +
        Number(snap.staking_yield_apy).toFixed(1) +
        "% (income — not price)</p>";
    }
    if (snap.price_change_7d != null) {
      html +=
        '<p class="time-capsule-modal__snap">Token price 7d: ' +
        Number(snap.price_change_7d).toFixed(1) +
        "%</p>";
    }
    if (snap.yield_trap) {
      html += '<p class="time-capsule-modal__warn">Yield trap at call time</p>';
    }
    var judges = cap.judge_scores_at_creation;
    if (judges && typeof judges === "object") {
      html += '<ul class="time-capsule-modal__judges">';
      Object.keys(judges).forEach(function (name) {
        var row = judges[name] || {};
        var score = row.confidence != null ? row.confidence : row.score;
        html +=
          "<li>" +
          esc(name) +
          (score != null ? " · " + esc(Number(score).toFixed(2)) : "") +
          "</li>";
      });
      html += "</ul>";
    }
    body.innerHTML = html;
    if (copyBtn) {
      copyBtn.hidden = false;
      copyBtn.onclick = function () {
        var text = payload.share_text || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(function () {});
        }
      };
    }
    modal.hidden = false;
  }

  function openCapsule(predictionId) {
    if (!predictionId) return;
    fetch("/api/predictions/capsule/" + encodeURIComponent(predictionId))
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(renderCapsule)
      .catch(function () {
        renderCapsule(null);
      });
  }

  function bindStoryStrip() {
    var list = document.getElementById("story-strip-list");
    if (!list || list.dataset.capsuleBound === "1") return;
    list.dataset.capsuleBound = "1";
    list.addEventListener("click", function (e) {
      var item = e.target.closest("[data-prediction-id]");
      if (!item) return;
      openCapsule(item.getAttribute("data-prediction-id"));
    });
  }

  function patchObserver() {
    bindStoryStrip();
    var body = document.getElementById("story-strip-body");
    if (!body || body.dataset.capsuleObs === "1") return;
    body.dataset.capsuleObs = "1";
    try {
      new MutationObserver(bindStoryStrip).observe(body, { childList: true, subtree: true });
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", patchObserver);
  } else {
    patchObserver();
  }

  window.SimiTimeCapsule = { open: openCapsule, close: closeModal };
})();
