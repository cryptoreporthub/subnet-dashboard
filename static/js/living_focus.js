/** §27-3a–c — Living Focus + Public Self-Update */
(function () {
  'use strict';

  var root = document.getElementById('section-living-focus');
  if (!root) return;

  var bodyEl = document.getElementById('living-focus-body');
  var learnEl = document.getElementById('living-focus-learn');
  var switcherEl = document.getElementById('living-focus-switcher');
  var ctaEl = document.getElementById('living-focus-cta');
  var subEl = document.getElementById('living-focus-sub');
  var focusNetuid = null;
  var focusName = '';
  var audited = false;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function subnetName(sn, netuid) {
    var n = sn && (sn.name || sn.subnet_name);
    if (!n || String(n).toLowerCase() === 'none' || /^snnone$/i.test(String(n))) {
      return 'SN' + netuid;
    }
    return String(n);
  }

  function fetchJson(url, ms) {
    var ctrl = new AbortController();
    var t = setTimeout(function () { ctrl.abort(); }, ms || 12000);
    return fetch(url, { headers: { Accept: 'application/json' }, signal: ctrl.signal })
      .then(function (r) { return r.json(); })
      .finally(function () { clearTimeout(t); });
  }

  function pickFocusNetuid(dailyPick) {
    var pick = dailyPick && dailyPick.pick;
    var cand = dailyPick && dailyPick.candidate;
    var sn = (pick && pick.subnet) || (cand && cand.subnet) || {};
    var n = sn.netuid != null ? Number(sn.netuid) : null;
    audited = !!(pick && pick.subnet);
    return n;
  }

  function setFocus(netuid, name) {
    if (netuid == null) return;
    focusNetuid = Number(netuid);
    focusName = name || ('SN' + focusNetuid);
    root.setAttribute('data-focus-netuid', String(focusNetuid));
    window.LivingFocus = window.LivingFocus || {};
    window.LivingFocus.netuid = focusNetuid;
    window.LivingFocus.name = focusName;
    var inv = document.getElementById('inv-netuid');
    if (inv) inv.value = String(focusNetuid);
    document.dispatchEvent(new CustomEvent('living-focus:change', { detail: { netuid: focusNetuid, name: focusName } }));
  }

  function judgeBar(label, score, contested) {
    var pct = Math.max(0, Math.min(100, Number(score || 0) * 100));
    return (
      '<div class="living-focus__judge' + (contested ? ' living-focus__judge--contested' : '') + '">' +
      '<span class="living-focus__judge-label">' + esc(label) + '</span>' +
      '<span class="living-focus__judge-score">' + (score != null ? Number(score).toFixed(2) : '—') + '</span>' +
      '<span class="living-focus__judge-bar" style="--pct:' + pct + '%"></span>' +
      '</div>'
    );
  }

  function renderJudges(data, action) {
    if (!bodyEl) return;
    if (!data || data.error) {
      bodyEl.innerHTML = '<p class="living-focus__empty">Focus judges unavailable.</p>';
      return;
    }
    var consensus = data.consensus || {};
    var contested = !!consensus.contested || (consensus.agreement != null && consensus.agreement < 0.5);
    var split = contested ? ' · Council split' : '';
    if (subEl) {
      subEl.textContent = (audited ? 'Audited pick' : 'Candidate only') + split;
    }
  var html =
      '<header class="living-focus__header">' +
      '<h3 class="living-focus__name">' + esc(focusName) + ' <span class="living-focus__sn">SN' + focusNetuid + '</span></h3>' +
      '<span class="living-focus__action badge-' + (action === 'LONG' ? 'buy' : action === 'SHORT' ? 'sell' : 'watch') + '">' + esc(action || 'HOLD') + '</span>' +
      '</header>';
    if (contested) {
      html += '<p class="living-focus__contention">Council split — judges disagree on this subnet.</p>';
    }
    html += '<div class="living-focus__judges">' +
      judgeBar('Oracle', (data.oracle || {}).score, contested) +
      judgeBar('Echo', (data.echo || {}).score, contested) +
      judgeBar('Pulse', (data.pulse || {}).score, contested) +
      '</div>';
    if (consensus.verdict) {
      html += '<p class="living-focus__verdict">Consensus: <strong>' + esc(consensus.verdict) + '</strong>' +
        (consensus.agreement != null ? ' · agreement ' + Number(consensus.agreement).toFixed(2) : '') +
        '</p>';
    }
    bodyEl.innerHTML = html;
    if (ctaEl) ctaEl.hidden = false;
  }

  function renderChips(chips) {
    var chipRow = document.getElementById('living-focus-chips');
    if (!chipRow) {
      chipRow = document.createElement('div');
      chipRow.id = 'living-focus-chips';
      chipRow.className = 'living-focus__chips';
      if (bodyEl) bodyEl.appendChild(chipRow);
    }
    var items = (chips || []).filter(Boolean).slice(0, 3);
    if (!items.length) {
      chipRow.innerHTML = '';
      chipRow.hidden = true;
      return;
    }
    chipRow.hidden = false;
    chipRow.innerHTML = items.map(function (c) {
      return '<span class="living-focus__chip living-focus__chip--' + esc(c.tone || 'neutral') + '">' + esc(c.label) + '</span>';
    }).join('');
  }

  function renderSwitcher(top) {
    if (!switcherEl || !top || !top.length) return;
    switcherEl.hidden = false;
    switcherEl.innerHTML =
      '<p class="living-focus__switcher-label">Switch focus</p>' +
      '<div class="living-focus__switcher-row">' +
      top.slice(0, 3).map(function (row) {
        var n = row.netuid != null ? Number(row.netuid) : null;
        if (n == null) return '';
        var nm = subnetName(row, n);
        var active = n === focusNetuid ? ' living-focus__switch--active' : '';
        return '<button type="button" class="living-focus__switch' + active + '" data-netuid="' + n + '" data-name="' + esc(nm) + '">' + esc(nm) + '</button>';
      }).join('') +
      '</div>';
    switcherEl.querySelectorAll('.living-focus__switch').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var n = Number(btn.getAttribute('data-netuid'));
        setFocus(n, btn.getAttribute('data-name') || ('SN' + n));
        refreshFocus();
      });
    });
  }

  function renderLearnStrip(trail, weights) {
    if (!learnEl) return;
    var row = null;
    (trail || []).some(function (ev) {
      if (!ev || ev.netuid != null && Number(ev.netuid) !== focusNetuid) return false;
      if (ev.event_type === 'prediction_resolved' || ev.event_type === 'weight_change') {
        row = ev;
        return true;
      }
      var payload = ev.payload || ev;
      if (payload && payload.netuid != null && Number(payload.netuid) === focusNetuid) {
        row = ev;
        return true;
      }
      return false;
    });
    if (!row) {
      learnEl.hidden = false;
      learnEl.innerHTML = '<p class="living-focus__learn-empty">No graded beat on this SN yet — appears after resolver tick.</p>';
      return;
    }
    var payload = row.payload || row;
    var correct = payload.correct;
    var grade = correct === true ? 'HIT' : correct === false ? 'MISS' : 'GRADED';
    var expert = payload.expert || payload.signal || '';
    var before = payload.before;
    var after = payload.after;
    var delta = before != null && after != null ? (Number(after) - Number(before)).toFixed(2) : '';
    var predId = payload.prediction_id || row.prediction_id || row.id;
    var move = '';
    if (payload.predicted_pct != null && payload.actual_pct != null) {
      move = ' · expected ' + Number(payload.predicted_pct).toFixed(1) + '% → actual ' + Number(payload.actual_pct).toFixed(1) + '%';
    }
    var w = weights && expert ? weights[expert] : null;
    var html =
      '<div class="living-focus__learn-strip">' +
      '<h4 class="living-focus__learn-title">Last learn (Focus SN' + focusNetuid + ')</h4>' +
      '<p class="living-focus__learn-grade">' + esc(grade) + move + '</p>';
    if (expert && (before != null || w != null)) {
      html += '<p class="living-focus__learn-nudge">' + esc(expert) + ' ' +
        (before != null ? Number(before).toFixed(2) : '?') + ' → ' +
        (after != null ? Number(after).toFixed(2) : (w != null ? Number(w).toFixed(2) : '?')) +
        (delta ? ' (' + (Number(delta) >= 0 ? '+' : '') + delta + ')' : '') +
        '</p>';
    }
    html += '<div class="living-focus__learn-actions">';
    if (predId) {
      html += '<button type="button" class="btn-secondary living-focus__replay" data-prediction-id="' + esc(predId) + '">Replay time capsule</button>';
    }
    if (payload.share_page_url) {
      html += '<button type="button" class="btn-secondary living-focus__share" data-share-url="' + esc(payload.share_page_url) + '">Share graded call</button>';
    }
    html += '</div></div>';
    learnEl.hidden = false;
    learnEl.innerHTML = html;
    learnEl.querySelectorAll('.living-focus__replay').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-prediction-id');
        if (id && window.SimiTimeCapsule && window.SimiTimeCapsule.open) {
          window.SimiTimeCapsule.open(id);
        }
      });
    });
    learnEl.querySelectorAll('.living-focus__share').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var path = btn.getAttribute('data-share-url');
        if (path && navigator.clipboard) {
          navigator.clipboard.writeText(window.location.origin + path).catch(function () {});
        }
      });
    });
  }

  function loadChips() {
    var chips = [];
    return Promise.all([
      fetchJson('/api/scenario-memory', 8000).catch(function () { return null; }),
      fetchJson('/api/ruggers/subnet/' + focusNetuid, 8000).catch(function () { return null; }),
      fetchJson('/api/postmortems?limit=1', 8000).catch(function () { return null; }),
    ]).then(function (res) {
      var scen = res[0];
      if (scen && scen.regime) {
        chips.push({ label: 'Regime: ' + scen.regime, tone: 'neutral' });
      } else if (scen && scen.stats && scen.stats.dominant_regime) {
        chips.push({ label: 'Regime: ' + scen.stats.dominant_regime, tone: 'neutral' });
      }
      var rug = res[1];
      if (rug && rug.risk_level) {
        chips.push({ label: 'Rug risk: ' + rug.risk_level, tone: rug.risk_level === 'high' ? 'warn' : 'neutral' });
      }
      var pm = res[2];
      var posts = (pm && pm.postmortems) || [];
      if (posts.length) {
        var p = posts[0];
        chips.push({ label: 'Autopsy: ' + (p.judge || p.title || 'latest'), tone: 'muted' });
      }
      renderChips(chips);
    });
  }

  function refreshFocus() {
    if (focusNetuid == null) return Promise.resolve();
    var action = 'HOLD';
    return Promise.all([
      fetchJson('/api/judges/' + focusNetuid, 15000),
      fetchJson('/api/calibration/status', 8000).catch(function () { return {}; }),
      fetchJson('/api/mindmap/trail?limit=40', 10000).catch(function () { return { trail: [] }; }),
      fetchJson('/api/daily-pick', 8000).catch(function () { return {}; }),
    ]).then(function (res) {
      var judges = res[0];
      var cal = res[1];
      var trail = (res[2] && res[2].trail) || [];
      var dp = res[3] || {};
      action = String(dp.action || 'HOLD').toUpperCase();
      renderJudges(judges, action);
      var weights = (cal.calibration && cal.calibration.expert_weights) || cal.expert_weights || {};
      renderLearnStrip(trail, weights);
      return loadChips();
    });
  }

  function init() {
    Promise.all([
      fetchJson('/api/daily-pick', 12000),
      fetchJson('/api/simivision', 12000).catch(function () { return {}; }),
    ]).then(function (res) {
      var dp = res[0] || {};
      var simi = res[1] || {};
      var top = (simi.data && simi.data.top) || simi.top || [];
      var n = pickFocusNetuid(dp);
      if (n == null && top.length && top[0].netuid != null) {
        n = Number(top[0].netuid);
        audited = false;
      }
      if (n == null) {
        if (bodyEl) bodyEl.innerHTML = '<p class="living-focus__empty">No focus subnet today — council has not cleared a pick.</p>';
        return;
      }
      var sn = (dp.pick && dp.pick.subnet) || (dp.candidate && dp.candidate.subnet) || top[0] || {};
      setFocus(n, subnetName(sn, n));
      renderSwitcher(top);
      return refreshFocus();
    }).catch(function () {
      if (bodyEl) bodyEl.innerHTML = '<p class="living-focus__empty">Living Focus unavailable.</p>';
    });
  }

  var proveBtn = document.getElementById('living-focus-prove-btn');
  if (proveBtn) {
    proveBtn.addEventListener('click', function () {
      var drawer = document.getElementById('market-drawer');
      if (drawer && !drawer.open) drawer.setAttribute('open', 'open');
      var inv = document.getElementById('section-investigation');
      if (inv) inv.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (window.InvestigationPanel && window.InvestigationPanel.runSellers) {
        window.InvestigationPanel.runSellers(focusNetuid);
      } else {
        var btn = document.getElementById('inv-sellers-btn');
        if (btn) btn.click();
      }
    });
  }

  window.LivingFocus = {
    get netuid() { return focusNetuid; },
    refresh: refreshFocus,
    setFocus: setFocus,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
