/** §21 L5 — mindmap story path (linear cause chain). */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderStoryPath(payload) {
    var chain = document.getElementById("story-path-chain");
    if (!chain) return;
    if (!payload || !payload.data_available || !payload.steps || !payload.steps.length) {
      var reason = payload && payload.reason === "no_pick"
        ? "No audited pick today — chain appears when council clears a call."
        : "Story path warming up.";
      chain.innerHTML = '<li class="story-path__empty" id="story-path-empty">' + esc(reason) + "</li>";
      return;
    }
    var html = "";
    payload.steps.forEach(function (step) {
      html +=
        '<li class="story-path__step story-path__step--' +
        esc(step.status || "done") +
        '">' +
        '<span class="story-path__label">' +
        esc(step.label || "Step") +
        "</span>" +
        '<span class="story-path__step-title">' +
        esc(step.title || "—") +
        "</span>";
      if (step.detail) {
        html += '<span class="story-path__detail">' + esc(step.detail) + "</span>";
      }
      html += "</li>";
    });
    chain.innerHTML = html;
  }

  function loadStoryPath() {
    fetch("/api/mindmap/story-path")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(renderStoryPath)
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadStoryPath);
  } else {
    loadStoryPath();
  }

  document.addEventListener("home-daily-call-updated", loadStoryPath);

  window.SimiStoryPath = { refresh: loadStoryPath, render: renderStoryPath };
})();
