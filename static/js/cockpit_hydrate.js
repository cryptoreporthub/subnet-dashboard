/* Hydrate cockpit sections from JSON APIs (homepage is a fast shell on Fly). */
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

  function fetchJsonTimeout(url, ms) {
    return new Promise(function (resolve, reject) {
      var ctrl = new AbortController();
      var timer = setTimeout(function () {
        ctrl.abort();
        reject(new Error('timeout'));
      }, ms);
      fetch(url, { headers: { Accept: 'application/json' }, signal: ctrl.signal })
        .then(function (r) {
          if (!r.ok) throw new Error(String(r.status));
          return r.json();
        })
        .then(function (data) {
          clearTimeout(timer);
          resolve(data);
        })
        .catch(function (err) {
          clearTimeout(timer);
          reject(err);
        });
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
    if (!pick) return;
    var sn = pick.subnet || {};
    var fc = confTier(payload.final_confidence != null ? payload.final_confidence : pick.confidence || 0);
    var act = String(payload.action || pick.action || 'HOLD').toUpperCase();
    var audit = payload.audit || pick.audit || {};
    var html =
      '<div class="hero-card">' +
      '<div class="pick-rank" style="font-size:24px;">★</div>' +
      '<div class="pick-name pick-name-lg hero-name">' + esc(sn.name || pickName(pick)) + '</div>' +
      '<div class="pick-meta hero-meta">SN' + esc(sn.netuid || pickNetuid(pick)) + '</div>' +
      '<div class="pick-row"><div class="conviction-wrap">' +
      '<div class="conviction-lbl">Final Confidence</div>' +
      '<div class="conviction-bar"><div class="conviction-fill ' + fc.tier + '" style="width:' + fc.conf + '%;"></div></div>' +
      '<div class="pred-line">score <b>' + fmt(pick.score || payload.score, 1) + '</b></div></div>' +
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

  function renderCouncilWeights(weights) {
    if (!weights || typeof weights !== 'object') return;
    var keys = Object.keys(weights);
    if (!keys.length) return;
    var cards = keys.map(function (name) {
      var w = Number(weights[name]) || 0;
      return (
        '<div class="expert card-soft card">' +
        '<div class="avatar">' + esc(name.charAt(0).toUpperCase()) + '</div>' +
        '<div class="name">' + esc(name) + '</div>' +
        '<div class="w">' + fmt(w, 3) + '</div>' +
        '<div class="wbar"><div class="wfill" style="width:' + Math.min(w / 2 * 100, 100) + '%;"></div></div>' +
        '<span class="bias neu">NEUTRAL</span></div>'
      );
    }).join('');
    replaceEmptyIn('section-council', '<div class="council-grid">' + cards + '</div>');
  }

  function renderKpi(stats) {
    if (!stats) return;
    var acc = Math.round((Number(stats.accuracy) || 0) * 1000) / 10;
    var section = document.getElementById('section-kpi');
    if (!section) return;
    var strip = section.querySelector('.kpi-strip');
    if (!strip) return;
    var vals = strip.querySelectorAll('.val');
    if (vals[0]) vals[0].textContent = acc + '%';
    if (vals[1]) vals[1].textContent = String(stats.pending || 0);
    if (vals[2]) vals[2].textContent = String(stats.resolved || 0);
    if (vals[3]) vals[3].textContent = String(stats.total_records || 0);
  }

  function renderHero(subnets) {
    if (!subnets || !subnets.length) return;
    var gainers = 0;
    var losers = 0;
    var chgSum = 0;
    var apySum = 0;
    var apyN = 0;
    subnets.forEach(function (sn) {
      var chg = Number(sn.price_change_24h) || 0;
      chgSum += chg;
      if (chg > 0) gainers += 1;
      else if (chg < 0) losers += 1;
      var apy = sn.apy != null ? Number(sn.apy) : null;
      if (apy != null) {
        apySum += apy;
        apyN += 1;
      }
    });
    replaceEmptyIn(
      'section-hero',
      '<div class="kpi-grid" style="grid-template-columns: repeat(6, 1fr);">' +
      '<div class="kpi-cell"><div class="k">Subnets</div><div class="v">' + subnets.length + '</div>' +
      '<div class="sub">' + gainers + ' gainers / ' + losers + ' losers</div></div>' +
      '<div class="kpi-cell"><div class="k">Avg 24h</div><div class="v">' + fmtSigned(chgSum / subnets.length) + '</div><div class="sub">24h change</div></div>' +
      '<div class="kpi-cell"><div class="k">Avg APY</div><div class="v">' + (apyN ? fmt(apySum / apyN * 100, 2) : '—') + '%</div><div class="sub">stake yield</div></div>' +
      '<div class="kpi-cell"><div class="k">Data</div><div class="v" style="font-size:15px;">TAOMARKETCAP</div><div class="sub">live feed</div></div>' +
      '</div>'
    );
    document.querySelectorAll('.src-tag b').forEach(function (el) {
      el.textContent = 'TAOMARKETCAP';
    });
  }

  function renderJudges(judges) {
    var panel = document.getElementById('judges-panel');
    if (!panel || !judges || !judges.length) return;
    function verdictClass(v) {
      if (v === 'bullish') return 'badge-buy';
      if (v === 'bearish') return 'badge-sell';
      return 'badge-watch';
    }
    var cards = judges.slice(0, 12).map(function (j) {
      var verdict = (j.consensus && j.consensus.verdict) || 'neutral';
      var score = j.consensus ? j.consensus.score : null;
      return (
        '<article class="card judge-summary" style="margin-bottom:10px;">' +
        '<div class="card-head"><h3>' + esc(j.name || ('SN' + j.netuid)) + '</h3>' +
        '<span class="badge ' + verdictClass(verdict) + '">' + esc(String(verdict).toUpperCase()) + '</span></div>' +
        '<div class="pick-meta">SN' + esc(j.netuid) + (score != null ? ' · consensus ' + Number(score).toFixed(2) : '') + '</div></article>'
      );
    }).join('');
    panel.innerHTML = '<div class="picks">' + cards + '</div><p class="pick-meta" style="margin-top:8px;">' + judges.length + ' subnets scored</p>';
  }

  function renderSignals(signals, alerts) {
    if (typeof window.__applySignalsPayload === 'function') {
      window.__applySignalsPayload(signals, alerts);
      return;
    }
    var root = document.getElementById('signals-feed-root');
    if (!root || !signals || !signals.length) return;
    var rows = signals.slice(0, 12).map(function (sig) {
      var st = String(sig.signal_type || 'neutral').toLowerCase();
      return '<tr><td>' + esc(sig.name || ('SN' + sig.subnet_id)) + '</td>' +
        '<td><span class="badge badge-watch">' + esc(st.toUpperCase()) + '</span></td>' +
        '<td>' + ((Number(sig.confidence) || 0) * 100).toFixed(1) + '%</td></tr>';
    }).join('');
    root.innerHTML = '<table class="tbl"><thead><tr><th>Subnet</th><th>Type</th><th>Conf</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function updateGroupData(hourPicks, dayPicks, trail, subnets) {
    var el = document.getElementById('subnet-group-data');
    if (!el) return;
    try {
      var data = JSON.parse(el.textContent);
      if (hourPicks && hourPicks.length) data.hour_picks = hourPicks;
      if (dayPicks && dayPicks.length) data.day_picks = dayPicks;
      if (trail && trail.length) data.trail = trail.slice(0, 20);
      if (subnets && subnets.length) data.roster = subnets.slice(0, 24);
      el.textContent = JSON.stringify(data);
      if (typeof window.__refreshSubnetGroups === 'function') window.__refreshSubnetGroups();
    } catch (e) {
      console.warn('[cockpit_hydrate] group data update failed', e);
    }
  }

  async function run() {
    if (document.documentElement.dataset.hydrate !== '1') return;

    var results = await Promise.allSettled([
      fetchJsonTimeout('/api/simivision', 12000),
      fetchJsonTimeout('/api/top-pick/hour', 12000),
      fetchJsonTimeout('/api/daily-pick', 12000),
      fetchJsonTimeout('/api/top-pick/day', 12000),
      fetchJsonTimeout('/api/mindmap/trail?limit=20', 12000),
      fetchJsonTimeout('/api/learning/stats', 8000),
      fetchJsonTimeout('/api/subnets', 15000),
      fetchJsonTimeout('/api/signals', 15000),
      fetchJsonTimeout('/api/alerts?refresh_checks=false', 8000),
      fetchJsonTimeout('/api/judges', 30000),
    ]);

    var hourPicks = [];
    var dayPicks = [];
    var trail = [];
    var subnets = [];

    if (results[0].status === 'fulfilled') {
      renderSimivision((results[0].value.data || {}).top || []);
    }
    if (results[1].status === 'fulfilled') hourPicks = (results[1].value.picks) || [];
    if (results[3].status === 'fulfilled') dayPicks = (results[3].value.picks) || [];
    if (results[2].status === 'fulfilled') renderDailyPick(results[2].value);
    renderHourDayPicks(hourPicks, dayPicks);
    if (results[4].status === 'fulfilled') {
      trail = results[4].value.trail || [];
      renderTrail(trail);
    }
    if (results[5].status === 'fulfilled') {
      var stats = results[5].value.data || {};
      renderKpi(stats);
      renderCouncilWeights(stats.expert_weights || {});
    }
    if (results[6].status === 'fulfilled') {
      subnets = results[6].value.subnets || [];
      renderHero(subnets);
    }
    if (results[7].status === 'fulfilled') {
      var sigPayload = results[7].value;
      var alertsPayload = results[8].status === 'fulfilled' ? results[8].value : {};
      renderSignals(sigPayload.signals || [], (alertsPayload.alerts) || []);
    }
    if (results[9].status === 'fulfilled') {
      renderJudges(results[9].value.judges || []);
    }

    updateGroupData(hourPicks, dayPicks, trail, subnets);
    console.log('[cockpit_hydrate] panels updated from APIs');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
