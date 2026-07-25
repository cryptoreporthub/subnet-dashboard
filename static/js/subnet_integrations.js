/** Bittensor subnet integrations — compact strip: ● Name (SN#) per service. */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function displayName(row) {
    var name = row.name || row.slug || '—';
    // Prefer short product names over "Finney mainnet" verbosity where useful.
    if (row.slug === 'bittensor') return 'Finney';
    if (row.slug === 'blockmachine') return 'Blockmachine';
    if (row.slug === 'desearch') return 'DeSearch';
    if (row.slug === 'chutes') return 'Chutes';
    if (row.slug === 'ditto') return 'Ditto';
    return name;
  }

  function statusWord(status) {
    if (status === 'connected') return 'live';
    if (status === 'reachable') return 'reachable';
    return 'offline';
  }

  function buildItem(row) {
    var status = row.status || 'offline';
    var name = displayName(row);
    var label = name;
    if (row.netuid != null && row.netuid !== '') {
      label = name + ' (SN' + row.netuid + ')';
    }
    var tip =
      label +
      ' — ' +
      statusWord(status) +
      (row.detail ? ' · ' + row.detail : '') +
      (row.role ? ' · ' + row.role : '');
    return (
      '<span class="subnet-int-item subnet-int-item--' +
      esc(status) +
      '" title="' +
      esc(tip) +
      '">' +
      '<span class="subnet-int-dot subnet-int-dot--' +
      esc(status) +
      '" aria-hidden="true"></span>' +
      '<span class="subnet-int-label">' +
      esc(label) +
      '</span>' +
      '</span>'
    );
  }

  function buildStrip(payload) {
    var rows = (payload && payload.integrations) || [];
    var connected = payload.connected_count != null ? payload.connected_count : 0;
    var total = payload.integration_total != null ? payload.integration_total : rows.length;
    var live = connected >= total && total > 0;
    var countLabel = live ? total + '/' + total + ' live' : connected + '/' + total + ' live';

    var items = rows.map(buildItem).join('');

    return (
      '<div class="subnet-int-strip' +
      (live ? ' subnet-int-strip--live' : '') +
      '" role="list" aria-label="Bittensor subnet integrations: ' +
      esc(countLabel) +
      '">' +
      '<span class="subnet-int-strip__brand">Built on Bittensor</span>' +
      '<span class="subnet-int-strip__items">' +
      items +
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
