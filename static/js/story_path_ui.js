/** §21 L5 — mindmap story path (linear cause chain) + home cause chain. */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderStepsInto(listEl, steps, emptyHtml) {
    if (!listEl) return;
    if (!steps || !steps.length) {
      listEl.innerHTML = emptyHtml;
      return;
    }
    var html = "";
    steps.forEach(function (step) {
      html +=
        '<li class="story-path__step story-path__step--' +
        esc(step.status || "done") +
        ' sr-cause-chain__step sr-cause-chain__step--' +
        esc(step.status || "done") +
        '">' +
        '<span class="story-path__label sr-cause-chain__lbl">' +
        esc(step.label || "Step") +
        "</span>" +
        '<span class="story-path__step-title sr-cause-chain__title">' +
        esc(step.title || "—") +
        "</span>";
      if (step.detail) {
        html +=
          '<span class="story-path__detail sr-cause-chain__detail">' +
          esc(step.detail) +
          "</span>";
      }
      html += "</li>";
    });
    listEl.innerHTML = html;
  }

  function renderStoryPath(payload) {
    var proChain = document.getElementById("story-path-chain");
    var homeChain = document.querySelector("#section-cause-chain .sr-cause-chain__list");
    var homeSection = document.getElementById("section-cause-chain");
    var homeEmpty = homeSection && homeSection.querySelector(".sr-cause-chain__empty");

    var available = !!(payload && payload.data_available && payload.steps && payload.steps.length);
    var emptyPro =
      '<li class="story-path__empty" id="story-path-empty">' +
      esc(
        payload && payload.reason === "no_pick"
          ? "No audited pick today — chain appears when council clears a call."
          : "Quiet — story path fills when council clears an audited pick."
      ) +
      "</li>";

    if (proChain) {
      renderStepsInto(proChain, available ? payload.steps : null, emptyPro);
    }

    if (homeSection) {
      if (available) {
        if (!homeChain) {
          if (homeEmpty) homeEmpty.remove();
          homeChain = document.createElement("ol");
          homeChain.className = "sr-cause-chain__list";
          homeSection.appendChild(homeChain);
        }
        if (homeEmpty) homeEmpty.hidden = true;
        renderStepsInto(homeChain, payload.steps.slice(0, 4), "");
      } else if (homeEmpty) {
        homeEmpty.hidden = false;
        homeEmpty.textContent =
          payload && payload.reason === "no_pick"
            ? "Quiet — chain appears when council clears an audited pick."
            : "Quiet — chain appears when council clears an audited pick.";
        if (homeChain) homeChain.innerHTML = "";
      } else if (homeChain) {
        homeChain.innerHTML =
          '<li class="sr-cause-chain__empty">Quiet — chain appears when council clears an audited pick.</li>';
      }
    }
  }

  function loadStoryPath() {
    var fetchJson = window.apiFetchJson || function (url) {
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; });
    };
    fetchJson("/api/mindmap/story-path", 12000)
      .then(renderStoryPath)
      .catch(function () {
        renderStoryPath({ data_available: false, reason: "error" });
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadStoryPath);
  } else {
    loadStoryPath();
  }

  document.addEventListener("home-daily-call-updated", loadStoryPath);
  document.addEventListener("living-focus:change", loadStoryPath);

  window.SimiStoryPath = { refresh: loadStoryPath, render: renderStoryPath };
})();
