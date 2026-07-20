/**
 * Weighing Room — peel toggle + name → dossier handoff.
 */
(function () {
  function goSubnet(netuid) {
    if (typeof window.switchToSubnet === "function") {
      window.switchToSubnet(String(netuid));
      return;
    }
    var url = new URL(window.location.href);
    url.searchParams.set("netuid", String(netuid));
    window.location.href = url.toString();
  }

  function bind(root) {
    if (!root) return;
    if (root.dataset.wrBound === "1") return;
    root.dataset.wrBound = "1";
    root.addEventListener("click", function (ev) {
      var nameLink = ev.target.closest(".wr-name__link");
      if (nameLink && root.contains(nameLink)) {
        ev.preventDefault();
        ev.stopPropagation();
        var nu = nameLink.getAttribute("data-wr-netuid");
        if (nu != null && nu !== "") goSubnet(nu);
        return;
      }
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
    var section = document.getElementById("section-simivision-picks");
    if (section) section.dataset.wrBound = "";
    bind(section);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("weighing-room-updated", boot);
})();
