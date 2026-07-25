/** Bittensor subnet integrations — status bar + corner (SN22/50/64/118). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function renderRow(row) {
    var status = row.status || 'offline';
    var label = status === 'connected' ? 'Connected' : status === 'reachable' ? 'Reachable' : 'Offline';
    return (
      '<span class="subnet-int-chip subnet-int-chip--' +
      esc(status) +
      '" role="listitem" title="' +
      esc(row.role || '') +
      ' — ' +
      esc(row.detail || '') +
      '">' +
      '<span class="subnet-int-dot" aria-hidden="true"></span>' +
      '<span class="subnet-int-label">SN' +
      esc(row.netuid) +
      ' · ' +
      esc(row.name) +
      '</span>' +
      '<span class="subnet-int-state">' +
      esc(label) +
      '</span>' +
      '</span>'
    );
  }

  function renderCandidates(candidates, max) {
    if (!candidates || !candidates.length) return '';
    var top = candidates.slice(0, max || 4);
    var more = candidates.length - top.length;
    var chips = top
      .map(function (c) {
        return (
          '<span class="subnet-int-chip subnet-int-chip--candidate" title="' +
          esc(c.description || c.category || '') +
          ' · TaonSquare catalog">' +
          '<span class="subnet-int-dot" aria-hidden="true"></span>' +
          '<span class="subnet-int-label">SN' +
          esc(c.netuid) +
          ' · ' +
          esc(c.name) +
          '</span>' +
          '<span class="subnet-int-state">Next</span>' +
          '</span>'
        );
      })
      .join('');
    var tail =
      more > 0
        ? '<span class="subnet-int-more">+' + esc(more) + ' more</span>'
        : '';
    return (
      '<span class="subnet-int-subheading">Could connect next</span>' + chips + tail
    );
  }

  function buildInner(payload, opts) {
    opts = opts || {};
    var rows = (payload && payload.integrations) || [];
    var connected = payload.connected_count != null ? payload.connected_count : 0;
    var target = payload.target_minimum != null ? payload.target_minimum : 3;
    var summary =
      connected >= target
        ? connected + ' subnets connected'
        : connected + ' / ' + target + ' connected';
    return (
      '<div class="subnet-int-inner" role="list" aria-label="Bittensor subnet integrations">' +
      '<span class="subnet-int-heading">Built on Bittensor</span>' +
      rows.map(renderRow).join('') +
      (opts.showCandidates ? renderCandidates(payload.candidates, opts.candidateMax) : '') +
      '<span class="subnet-int-summary" title="Launch target: at least ' +
      esc(target) +
      ' live subnet integrations">' +
      esc(summary) +
      '</span>' +
      '</div>'
    );
  }

  function render(payload) {
    var rows = (payload && payload.integrations) || [];
    var connected = payload.connected_count != null ? payload.connected_count : 0;
    var bar = document.getElementById('subnetIntegrationsBar');
    var barInner = document.getElementById('subnetIntegrationsBarInner');
    var corner = document.getElementById('subnetIntegrationsCorner');
    var footerCount = document.getElementById('footer-integrations-count');

    if (!rows.length) {
      if (bar) bar.hidden = true;
      if (corner) corner.hidden = true;
      return;
    }

    if (bar && barInner) {
      bar.hidden = false;
      barInner.innerHTML = buildInner(payload, { showCandidates: false });
    }
    if (corner) {
      corner.hidden = false;
      corner.innerHTML = buildInner(payload, { showCandidates: true, candidateMax: 3 });
    }
    if (footerCount) {
      footerCount.textContent = String(connected) + '/4';
    }
  }

  function poll() {
    fetch('/api/subnet-integrations', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(render)
      .catch(function () {
        var bar = document.getElementById('subnetIntegrationsBar');
        var corner = document.getElementById('subnetIntegrationsCorner');
        if (bar) bar.hidden = true;
        if (corner) corner.hidden = true;
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') poll();
  });
  setInterval(function () {
    if (document.visibilityState !== 'hidden') poll();
  }, 180000);
})();
