/** §20.T2 — copy/download letter markdown (no email) */
(function () {
  "use strict";

  function wire(copyId, downloadId, defaultName) {
    var copyBtn = document.getElementById(copyId);
    var dlBtn = document.getElementById(downloadId);
    if (!copyBtn && !dlBtn) return { setMarkdown: function () {} };

    function setEnabled(on) {
      if (copyBtn) copyBtn.disabled = !on;
      if (dlBtn) dlBtn.disabled = !on;
    }

    function setMarkdown(markdown, filename) {
      var md = String(markdown || "").trim();
      var name = (filename || defaultName || "letter") + ".md";
      if (!md) {
        setEnabled(false);
        return;
      }
      setEnabled(true);
      if (copyBtn) {
        copyBtn.onclick = function () {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(md).catch(function () {});
          }
        };
      }
      if (dlBtn) {
        dlBtn.onclick = function () {
          var blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = name;
          a.rel = "noopener";
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        };
      }
    }

    setEnabled(false);
    return { setMarkdown: setMarkdown };
  }

  window.LetterExport = {
    weekly: wire("weekly-letter-copy", "weekly-letter-download", "weekly-letter"),
    daily: wire("daily-letter-copy", "daily-letter-download", "daily-recap"),
  };
})();
