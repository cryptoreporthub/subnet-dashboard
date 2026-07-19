/**
 * Weighing Room — peel toggle for Conviction Board rows.
 */
(function () {
  function bind(root) {
    if (!root || root.dataset.wrBound === "1") return;
    root.dataset.wrBound = "1";
    root.addEventListener("click", function (ev) {
      var face = ev.target.closest(".wr-row__face");
      if (!face || !root.contains(face)) return;
      var row = face.closest(".wr-row");
      if (!row) return;
      var peel = row.querySelector(".wr-peel");
      var open = !row.classList.contains("is-open");
      row.classList.toggle("is-open", open);
      face.setAttribute("aria-expanded", open ? "true" : "false");
      if (peel) {
        if (open) peel.removeAttribute("hidden");
        else peel.setAttribute("hidden", "");
      }
    });
  }

  function boot() {
    bind(document.getElementById("section-simivision-picks"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("weighing-room-updated", boot);
})();
