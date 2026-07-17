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
      '<button type="button" class="time-capsule-modal__copy" id="time-capsule-copy">Copy text</button>' +
      '<button type="button" class="time-capsule-modal__link" id="time-capsule-link" hidden>Copy link</button>' +
      '<button type="button" class="time-capsule-modal__image" id="time-capsule-image" hidden>Save PNG</button>' +
      '<button type="button" class="time-capsule-modal__share" id="time-capsule-share" hidden>Share link</button>' +
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

  function renderGradedCallCard(payload) {
    var cap = payload.capsule || {};
    var pred = payload.prediction || {};
    var snap = cap.subnet_snapshot || {};
    var name = pred.name || cap.name || (pred.netuid != null ? "SN" + pred.netuid : "Subnet");
    var verdict = cap.correct === true ? "HIT" : cap.correct === false ? "MISS" : "GRADED";
    var verdictClass =
      cap.correct === true ? "graded-call-card__verdict--hit" : "graded-call-card__verdict--miss";

    var html =
      '<article class="graded-call-card" id="graded-call-card" aria-label="Shareable graded call">' +
      '<p class="graded-call-card__brand">SimiVision · graded call</p>' +
      '<div class="graded-call-card__head">' +
      '<h4 class="graded-call-card__name">' +
      esc(name) +
      "</h4>" +
      '<span class="graded-call-card__verdict ' +
      verdictClass +
      '">' +
      esc(verdict) +
      "</span></div>";

    if (cap.predicted_pct != null && cap.actual_pct != null) {
      html +=
        '<p class="graded-call-card__move">' +
        '<span class="graded-call-card__k">Expected</span> ' +
        Number(cap.predicted_pct).toFixed(1) +
        "%" +
        '<span class="graded-call-card__arrow">→</span>' +
        '<span class="graded-call-card__k">Actual</span> ' +
        Number(cap.actual_pct).toFixed(1) +
        "%</p>";
    }

    if (cap.statement) {
      html += '<p class="graded-call-card__stmt">' + esc(cap.statement) + "</p>";
    }

    html += '<div class="graded-call-card__tags">';
    if (snap.yield_trap) {
      html += '<span class="graded-call-card__tag graded-call-card__tag--warn">yield trap</span>';
    }
    if (snap.price_change_7d != null && Math.abs(Number(snap.price_change_7d)) >= 1) {
      var v = Number(snap.price_change_7d);
      html +=
        '<span class="graded-call-card__tag">price 7d ' +
        (v > 0 ? "+" : "") +
        v.toFixed(0) +
        "%</span>";
    }
    var driver = snap.return_driver || snap.dominant_driver;
    if (driver) {
      html +=
        '<span class="graded-call-card__tag">' + esc(String(driver).replace(/_/g, " ")) + "</span>";
    }
    html += "</div>";

    html +=
      '<p class="graded-call-card__foot">Direction graded on token price — staking APY is income, not price.</p>' +
      "</article>";
    return html;
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
    var html = renderGradedCallCard(payload);
    html += '<div class="time-capsule-modal__details">';
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
    html += "</div>";
    body.innerHTML = html;
    if (copyBtn) {
      copyBtn.hidden = false;
      copyBtn.textContent = "Copy text";
      copyBtn.onclick = function () {
        var text = payload.share_text || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(function () {});
        }
      };
      var imageBtn = document.getElementById("time-capsule-image");
      var imageUrl = payload.share_image_png_url || payload.share_image_url;
      if (imageBtn && imageUrl) {
        imageBtn.hidden = false;
        imageBtn.onclick = function () {
          var link = document.createElement("a");
          link.href = imageUrl;
          link.download = payload.share_image_png_url
            ? "simivision-graded-call.png"
            : "simivision-graded-call.svg";
          link.rel = "noopener";
          document.body.appendChild(link);
          link.click();
          link.remove();
        };
      } else if (imageBtn) {
        imageBtn.hidden = true;
      }
      var linkBtn = document.getElementById("time-capsule-link");
      if (linkBtn && payload.share_page_url) {
        linkBtn.hidden = false;
        linkBtn.onclick = function () {
          var url = window.location.origin + payload.share_page_url;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).catch(function () {});
          }
        };
      } else if (linkBtn) {
        linkBtn.hidden = true;
      }
      var shareBtn = document.getElementById("time-capsule-share");
      if (shareBtn && navigator.share) {
        shareBtn.hidden = false;
        shareBtn.onclick = function () {
          var shareUrl = payload.share_page_url
            ? window.location.origin + payload.share_page_url
            : window.location.href;
          var sharePayload = {
            title: "SimiVision graded call",
            text: payload.share_text || "",
            url: shareUrl,
          };
          var fileUrl = payload.share_image_png_url || payload.share_image_url;
          if (fileUrl && navigator.canShare) {
            fetch(fileUrl)
              .then(function (r) {
                return r.ok ? r.blob() : null;
              })
              .then(function (blob) {
                if (!blob) {
                  return navigator.share(sharePayload);
                }
                var isPng = Boolean(payload.share_image_png_url);
                var file = new File(
                  [blob],
                  isPng ? "simivision-graded-call.png" : "simivision-graded-call.svg",
                  { type: isPng ? "image/png" : "image/svg+xml" }
                );
                if (navigator.canShare({ files: [file] })) {
                  return navigator.share({
                    title: sharePayload.title,
                    text: sharePayload.text,
                    files: [file],
                  });
                }
                return navigator.share(sharePayload);
              })
              .catch(function () {
                navigator.share(sharePayload).catch(function () {});
              });
          } else {
            navigator.share(sharePayload).catch(function () {});
          }
        };
      } else if (shareBtn) {
        shareBtn.hidden = true;
      }
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
      var shareBtn = e.target.closest(".story-strip__share");
      if (shareBtn) {
        e.stopPropagation();
        var path = shareBtn.getAttribute("data-share-url");
        if (path && navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(window.location.origin + path).catch(function () {});
        }
        return;
      }
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
