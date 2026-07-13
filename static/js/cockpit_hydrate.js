/* Hydrate empty/degraded cockpit sections from fast JSON APIs (prod shell fallback). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function fmt(n, d) {
    d = d === undefined ? 2 : d;
    if (n == null || isNaN(n)) return '—';
    return Number(n).toFixed(d);
  }

  function fmtSigned(n, d) {
    n = Number(n) || 0;
    return (n >= 0 ? '+' : '') + n.toFixed(d === undefined ? 2 : d) + '%';
  }

  function confTier(conf) {
    var c = Number(conf);
    if (c <= 1) c *= 100;
    c = Math.round(c);
    if (c > 75) return { tier: 'tier-cyan', conf: c };
    if (c > 55) return { tier: 'tier-lime', conf: c };
    if (c > 35) return { tier: 'tier-gold', conf: c };
    return { tier: 'tier-red', conf: c };
  }

  function recBadge(rec) {
    var r = String(rec || 'WATCH').toUpperCase();
    if (r === 'BUY') return 'badge-buy';
    if (r === 'SELL') return 'badge-sell';
    if (r === 'HOLD') return 'badge-hold';
    return 'badge-watch';
  }

  function fetchJson(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  function replaceEmptyIn(sectionId, html) {
    var section = document.getElementById(sectionId);
    if (!section) return;
    var empty = section.querySelector('.empty');
    if (!empty) return;
    var host = empty.closest('.card-muted') || empty.parentElement;
    if (host) host.outerHTML = html;
  }

  function pickName(pick) {
    var sn = pick.subnet || {};
    return pick.name || sn.name || ('SN' + (pick.netuid || sn.netuid || '?'));
  }

  function pickNetuid(pick) {
    var sn = pick.subnet || {};
    return pick.netuid != null ? pick.netuid : sn.netuid;
  }

  function renderSimivision(top) {
    if (!top || !top.length) return;
    var cards = top.map(function (pick, idx) {
      var t = confTier(pick.conviction || 0);
      var rec = String(pick.recommendation || 'WATCH').toUpperCase();
      return (
        '<div class="pick-card">' +
        '<div class="pick-rank">#' + esc(pick.rank || idx + 1) + '</div>' +
        '<div class="pick-name pick-name-lg">' + esc(pick.name || 'SN' + pick.netuid) + '</div>' +
        '<div class="pick-meta">SN' + esc(pick.netuid) + ' · ' + fmt(pick.emission, 2) + ' TAO/day · ' + fmt(pick.apy, 1) + '% APY</div>' +
        '<div class="pick-row"><div class="conviction-wrap">' +
        '<div class="conviction-lbl">Conviction</div>' +
        '<div class="conviction-bar"><div class="conviction-fill ' + t.tier + '" style="width:' + t.conf + '%;"></div></div>' +
        '<div class="pred-line">' + fmtSigned(pick.price_change_24h) + ' 24h</div></div>' +
        '<div class="conv-ring ' + t.tier + '" style="--ring-pct:' + t.conf + ';"><div class="conv-ring-val">' + t.conf + '</div></div></div>' +
        '<div class="tags" style="margin-top:12px;"><span class="badge ' + recBadge(rec) + '">' + esc(rec) + '</span></div></div>'
      );
    }).join('');
    replaceEmptyIn('section-simivision-picks', '<div class="picks">' + cards + '</div>');
  }

  function renderDailyPick(payload) {
    if (!payload) return;
    var pick = payload.pick;
    var sn = (pick && pick.subnet) || {};
    if (!sn.netuid && !pick) return;
    var fc = confTier(payload.final_confidence != null ? payload.final_confidence : (pick && pick.confidence) || 0);
    var act = String(payload.action || (pick && pick.action) || 'HOLD').toUpperCase();
    var audit = payload.audit || (pick && pick.audit) || {};
    var html =
      '<div class="hero-card">' +
      '<div class="pick-rank" style="font-size:24px;">★</div>' +
      '<div class="pick-name pick-name-lg hero-name">' + esc(sn.name || pickName(pick || {})) + '</div>' +
      '<div class="pick-meta hero-meta">SN' + esc(sn.netuid || pickNetuid(pick || {})) + '</div>' +
      '<div class="pick-row"><div class="conviction-wrap">' +
      '<div class="conviction-lbl">Final Confidence</div>' +
      '<div class="conviction-bar"><div class="conviction-fill ' + fc.tier + '" style="width:' + fc.conf + '%;"></div></div>' +
      '<div class="pred-line">score <b>' + fmt((pick && pick.score) || payload.score, 1) + '</b></div></div>' +
      '<div class="conv-ring ' + fc.tier + '" style="--ring-pct:' + fc.conf + ';"><div class="conv-ring-val">' + fc.conf + '</div></div></div>' +
      '<div class="tags" style="margin-top:12px;"><span class="badge ' + recBadge(act) + '">' + esc(act) + '</span>' +
      (audit.approved ? '<span class="hero-audit">AUDIT PASSED</span>' : '') +
      '</div></div>';
    replaceEmptyIn('section-daily-pick', html);
  }

  function renderPickCards(picks) {
    return (picks || []).map(function (pick, idx) {
      var t = confTier(pick.confidence || 0);
      return (
        '<div class="pick-card"><div class="pick-rank">#' + (idx + 1) + '</div>' +
        '<div class="pick-name">' + esc(pickName(pick)) + '</div>' +
        '<div class="pick-meta">SN' + esc(pickNetuid(pick)) + ' · score <b class="accent-bright">' + fmt(pick.score, 1) + '</b></div>' +
        '<div class="conviction-bar"><div class="conviction-fill ' + t.tier + '" style="width:' + t.conf + '%;"></div></div></div>'
      );
    }).join('');
  }

  function renderHourDayPicks(hourPicks, dayPicks) {
    if (!(hourPicks && hourPicks.length) && !(dayPicks && dayPicks.length)) return;
    var html =
      '<div class="two-col">' +
      '<div class="card"><div class="card-head"><h3>Hour Horizon</h3><span class="src-tag">top ' + (hourPicks || []).length + ' · 1h</span></div>' +
      '<div class="picks">' + renderPickCards(hourPicks) + '</div></div>' +
      '<div class="card"><div class="card-head"><h3>Day Horizon</h3><span class="src-tag">top ' + (dayPicks || []).length + ' · 24h</span></div>' +
      '<div class="picks">' + renderPickCards(dayPicks) + '</div></div></div>';
    replaceEmptyIn('section-picks', html);
  }

  function trailChip(val) {
    if (val == null || val === '') return '—';
    if (typeof val === 'object') {
      if (val.accuracy != null) return 'accuracy ' + fmt(Number(val.accuracy) * 100, 1) + '%';
      if (val.prediction_id) return String(val.prediction_id).slice(0, 12);
      return JSON.stringify(val).slice(0, 48);
    }
    return String(val);
  }

  function renderTrail(trail) {
    if (!trail || !trail.length) return;
    var items = trail.slice(0, 20).map(function (t) {
      return (
        '<div class="trail-item">' +
        '<div class="trail-time">' + esc(t.time || '') + '</div>' +
        '<div class="trail-net">' + esc(t.subnet || (t.netuid != null ? 'SN' + t.netuid : '—')) + '</div>' +
        '<div class="trail-flow">' +
        '<span class="flow-chip">' + esc(trailChip(t.evidence)) + '</span>' +
        '<span class="flow-arrow">→</span>' +
        '<span class="flow-chip">' + esc(t.signal || t.event_type || '—') + '</span>' +
        '<span class="flow-arrow">→</span>' +
        '<span class="flow-chip">' + esc(t.decision || '—') + '</span></div>' +
        (t.prediction ? '<div class="trail-pred">' + esc(t.prediction) + '</div>' : '') +
        '</div>'
      );
    }).join('');
    replaceEmptyIn(
      'section-trail',
      '<div class="card"><div class="trail-counter">Trail entries: <b>' + trail.length + '</b></div><div class="trail">' + items + '</div></div>'
    );
  }

  function updateGroupData(hourPicks, dayPicks, trail) {
    var el = document.getElementById('subnet-group-data');
    if (!el) return;
    try {
      var data = JSON.parse(el.textContent);
      if (hourPicks && hourPicks.length) data.hour_picks = hourPicks;
      if (dayPicks && dayPicks.length) data.day_picks = dayPicks;
      if (trail && trail.length) data.trail = trail.slice(0, 20);
      el.textContent = JSON.stringify(data);
      if (typeof window.__refreshSubnetGroups === 'function') window.__refreshSubnetGroups();
    } catch (e) {
      console.warn('[cockpit_hydrate] group data update failed', e);
    }
  }

  function needsHydrate() {
    if (document.documentElement.dataset.hydrate === '1') return true;
    return !!document.querySelector(
      '#section-simivision-picks .empty, #section-daily-pick .empty, #section-picks .empty, #section-trail .empty'
    );
  }

  function normalizeHourPicks(resp) {
    return (resp && resp.picks) || [];
  }

  function normalizeDayPicks(resp) {
    return (resp && resp.picks) || [];
  }

  async function run() {
    if (!needsHydrate()) return;

    var results = await Promise.allSettled([
      fetchJson('/api/simivision'),
      fetchJson('/api/top-pick/hour'),
      fetchJson('/api/daily-pick'),
      fetchJson('/api/top-pick/day'),
      fetchJson('/api/mindmap/trail?limit=20'),
    ]);

    if (results[0].status === 'fulfilled') {
      renderSimivision((results[0].value.data || {}).top || []);
    }
    var hourPicks = results[1].status === 'fulfilled' ? normalizeHourPicks(results[1].value) : [];
    var dayPicks = results[3].status === 'fulfilled' ? normalizeDayPicks(results[3].value) : [];
    if (results[2].status === 'fulfilled') renderDailyPick(results[2].value);
    renderHourDayPicks(hourPicks, dayPicks);
    if (results[4].status === 'fulfilled') {
      renderTrail(results[4].value.trail || []);
      updateGroupData(hourPicks, dayPicks, results[4].value.trail || []);
    } else {
      updateGroupData(hourPicks, dayPicks, []);
    }

    document.querySelectorAll('.src-tag b').forEach(function (el) {
      if (String(el.textContent).toUpperCase().indexOf('REGISTRY') !== -1) {
        el.textContent = 'TAOMARKETCAP';
      }
    });
    console.log('[cockpit_hydrate] panels updated from APIs');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
