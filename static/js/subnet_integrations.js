/** Bittensor subnet integrations — compact 5/5 status strip (no floating panel). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function shortLabel(row) {
    if (row.netuid == null || row.netuid === '') return esc(row.name || row.slug || '—');
    return 'SN' + esc(row.netuid);
  }

  function statusWord(status) {
    if (status === 'connected') return 'live';
    if (status === 'reachable') return 'reachable';
    return 'offline';
  }

  function buildStrip(payload) {
    var rows = (payload && payload.integrations) || [];
    var connected = payload.connected_count != null ? payload.connected_count : 0;
    var total = payload.integration_total != null ? payload.integration_total : rows.length;
    var live = connected >= total && total > 0;
    var countLabel = live ? total + '/' + total + ' live' : connected + '/' + total + ' live';

    var dots = rows
      .map(function (row) {
        var status = row.status || 'offline';
        var tip =
          (row.netuid != null ? 'SN' + row.netuid + ' · ' : '') +
          (row.name || '') +
          ' — ' +
          statusWord(status) +
          (row.detail ? ' · ' + row.detail : '');
        return (
          '<span class="subnet-int-dot subnet-int-dot--' +
          esc(status) +
          '" title="' +
          esc(tip) +
          '" role="img" aria-label="' +
          esc(tip) +
          '"></span>'
        );
      })
      .join('');

    var names = rows
      .map(function (row) {
        var status = row.status || 'offline';
        return (
          '<span class="subnet-int-name subnet-int-name--' +
          esc(status) +
          '" title="' +
          esc(row.role || row.detail || '') +
          '">' +
          shortLabel(row) +
          '</span>'
        );
      })
      .join('<span class="subnet-int-sep" aria-hidden="true">·</span>');

    return (
      '<div class="subnet-int-strip' +
      (live ? ' subnet-int-strip--live' : '') +
      '" role="status" aria-label="Bittensor subnet integrations: ' +
      esc(countLabel) +
      '">' +
      '<span class="subnet-int-strip__brand">Built on Bittensor</span>' +
      '<span class="subnet-int-strip__dots" aria-hidden="true">' +
      dots +
      '</span>' +
      '<span class="subnet-int-strip__names">' +
      names +
      '</span>' +
      '<span class="subnet-int-strip__count">' +
      esc(countLabel) +
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

    // Corner panel retired — compact strip only.
    if (corner) {
      corner.hidden = true;
      corner.innerHTML = '';
    }

    if (!rows.length) {
      if (bar) bar.hidden = true;
      return;
    }

    if (bar && barInner) {
      bar.hidden = false;
      barInner.innerHTML = buildStrip(payload);
    }
    if (footerCount) {
      var total = payload.integration_total != null ? payload.integration_total : rows.length;
      footerCount.textContent = String(connected) + '/' + String(total);
    }
  }

  function poll() {
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = null;
    if (ctrl) {
      timer = setTimeout(function () {
        try {
          ctrl.abort();
        } catch (e) {}
      }, 8000);
    }
    fetch('/api/subnet-integrations', {
      headers: { Accept: 'application/json' },
      signal: ctrl ? ctrl.signal : undefined,
    })
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
      })
      .finally(function () {
        if (timer) clearTimeout(timer);
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
