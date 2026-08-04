/** Branded desk empty states for hydrate panels (ponytail: one helper, no framework). */
(function (g) {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function buildDeskEmptyState(opts) {
    opts = opts || {};
    var kind = opts.kind || 'empty';
    if (kind !== 'warming' && kind !== 'error') kind = 'empty';
    var title = opts.title || '';
    var body = opts.body || '';
    var progressN = opts.progressN;
    var progressMax = opts.progressMax;
    var extra = opts.classExtra || '';
    var id = opts.id || '';
    var html =
      '<div class="desk-empty-state desk-empty-state--' +
      esc(kind) +
      (extra ? ' ' + esc(extra) : '') +
      '"' +
      (id ? ' id="' + esc(id) + '"' : '') +
      ' role="status">';
    html += '<span class="desk-empty-state__glyph" aria-hidden="true"></span>';
    html += '<div class="desk-empty-state__body">';
    if (title) html += '<p class="desk-empty-state__title">' + esc(title) + '</p>';
    if (body) html += '<p class="desk-empty-state__text">' + esc(body) + '</p>';
    if (progressN != null && progressMax != null && Number(progressMax) > 0) {
      var pct = Math.min(100, Math.round((Number(progressN) / Number(progressMax)) * 100));
      html +=
        '<p class="desk-empty-state__progress">Building sample — ' +
        esc(progressN) +
        '/' +
        esc(progressMax) +
        '</p>';
      html +=
        '<div class="desk-empty-state__bar" aria-hidden="true"><span style="width:' +
        pct +
        '%"></span></div>';
    }
    html += '</div></div>';
    return html;
  }

  g.buildDeskEmptyState = buildDeskEmptyState;
})(window);
