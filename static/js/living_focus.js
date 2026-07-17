/** §27-3a–c + §30 Living Focus + Public Self-Update */
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
  var cachedTrail = null;

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

  function parseFocusParam() {
    try {
      var params = new URLSearchParams(window.location.search);
      var raw = params.get('focus') || params.get('netuid');
      if (raw == null || raw === '') return null;
      var n = Number(raw);
      return isNaN(n) ? null : n;
    } catch (e) {
      return null;
    }
  }

  function scrollToFocus() {
    if (parseFocusParam() == null) return;
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function calibrationWeights(cal) {
    if (!cal || typeof cal !== 'object') return {};
    return cal.weights
      || (cal.calibration && cal.calibration.expert_weights)
      || cal.expert_weights
      || {};
  }

  function trailMatchesFocus(ev) {
    if (!ev) return false;
    if (ev.netuid != null && Number(ev.netuid) !== focusNetuid) return false;
    if (ev.event_type === 'prediction_resolved' || ev.event_type === 'weight_change') {
      if (ev.netuid == null) {
        var pl = ev.payload || ev;
        if (!pl || pl.netuid == null || Number(pl.netuid) !== focusNetuid) return false;
      }
      return true;
    }
    var payload = ev.payload || ev;
    return !!(payload && payload.netuid != null && Number(payload.netuid) === focusNetuid);
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

  function renderWeightLean(weights) {
    var entries = Object.keys(weights || {}).map(function (k) {
      return { name: k, w: Number(weights[k]) || 0 };
    }).sort(function (a, b) { return b.w - a.w; });
    if (!entries.length) return '';
    var top = entries[0];
    var maxW = Math.max.apply(null, entries.map(function (e) { return e.w; }).concat([0.1]));
    var rows = entries.slice(0, 4).map(function (e) {
      var pct = Math.min(100, (e.w / maxW) * 100);
      return (
        '<div class="living-focus__weight-row">' +
        '<span class="living-focus__weight-name">' + esc(e.name) + '</span>' +
        '<span class="living-focus__weight-val">' + e.w.toFixed(2) + '</span>' +
        '<span class="living-focus__weight-bar" style="--pct:' + pct + '%"></span>' +
        '</div>'
      );
    }).join('');
    return (
      '<div class="living-focus__weights" aria-label="Council weight lean">' +
      '<p class="living-focus__weights-label">Who drives picks · <strong>' + esc(top.name) + '</strong> leads</p>' +
      rows +
      '</div>'
    );
  }

  function dissentSummary(data) {
    var lanes = [
      { key: 'oracle', label: 'Oracle' },
      { key: 'echo', label: 'Echo' },
      { key: 'pulse', label: 'Pulse' },
    ];
    var scores = lanes.map(function (l) {
      return { label: l.label, score: Number((data[l.key] || {}).score) || 0 };
    }).sort(function (a, b) { return a.score - b.score; });
    if (scores.length < 2) return null;
    var lo = scores[0];
    var hi = scores[scores.length - 1];
    if (hi.score - lo.score < 0.08) return null;
    return lo.label + ' most bearish (' + lo.score.toFixed(2) + ') · ' +
      hi.label + ' most bullish (' + hi.score.toFixed(2) + ')';
  }

  function renderWhyNot(explain) {
    if (!explain || explain.verdict === 'published' || !explain.blockers || !explain.blockers.length) {
      return '';
    }
    var label = explain.verdict === 'gated_candidate' ? 'Why no audited long' : 'Why not today\'s pick';
    var items = explain.blockers.slice(0, 4).map(function (b) {
      return '<li>' + esc(b) + '</li>';
    }).join('');
    return (
      '<div class="living-focus__why-not" role="status">' +
      '<p class="living-focus__why-not-title">' + esc(label) + '</p>' +
      '<ul class="living-focus__why-not-list">' + items + '</ul>' +
      '</div>'
    );
  }

  function renderJudges(data, action, weights, explain) {
    if (!bodyEl) return;
    if (!data || data.error) {
      bodyEl.innerHTML = '<p class="living-focus__empty">Focus judges unavailable.</p>';
      return;
    }
    var consensus = data.consensus || {};
    var contested = !!consensus.contested || (consensus.agreement != null && consensus.agreement < 0.5);
    var split = contested ? ' · Council split' : '';
    var dissent = dissentSummary(data);
    if (subEl) {
      subEl.textContent = (audited ? 'Audited pick' : 'Candidate only') + split;
    }
    var html = '';
    if (contested) {
      html += '<p class="living-focus__contention">Council split — judges disagree on this subnet.</p>';
      if (dissent) {
        html += '<p class="living-focus__contention living-focus__contention--detail">' + esc(dissent) + '</p>';
      }
    }
    html +=
      '<header class="living-focus__header">' +
      '<h3 class="living-focus__name"><a href="/subnet/' + focusNetuid + '" class="living-focus__link">' + esc(focusName) + '</a> <span class="living-focus__sn">SN' + focusNetuid + '</span></h3>' +
      '<span class="living-focus__action badge-' + (action === 'LONG' ? 'buy' : action === 'SHORT' ? 'sell' : 'watch') + '">' + esc(action || 'HOLD') + '</span>' +
      '</header>';
    html += renderWhyNot(explain);
    html += '<motion.div class="living-focus__judges">' +
      judgeBar('Oracle', (data.oracle || {}).score, contested) +
      judgeBar('Echo', (data.echo || {}).score, contested) +
      judgeBar('Pulse', (data.pulse || {}).score, contested) +
      '</div>';
    html += renderWeightLean(weights);
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
      if (!trailMatchesFocus(ev)) return false;
      row = ev;
      return true;
    });
    if (!row) {
      learnEl.hidden = false;
      learnEl.innerHTML = '<p class="living-focus__learn-empty">No graded beat on this SN yet — appears after resolver tick.</p>';
      return;
    }
    var payload = row.payload || row;
    var correct = payload.correct;
    var grade = correct === true ? 'HIT' : correct === false ? 'MISS' : 'GRADED';
    var expert = payload.expert || payload.signal || payload.dial || '';
    var before = payload.before;
    var after = payload.after;
    var delta = before != null && after != null ? (Number(after) - Number(before)).toFixed(2) : '';
    var predId = payload.prediction_id || row.prediction_id || row.id;
    var move = '';
    if (payload.predicted_pct != null && payload.actual_pct != null) {
      move = ' · expected ' + Number(payload.predicted_pct).toFixed(1) + '% → actual ' + Number(payload.actual_pct).toFixed(1) + '%';
    }
    var dial = expert && expert.indexOf(':') >= 0 ? expert.split(':').pop() : expert;
    var w = weights && dial ? weights[dial] : (weights && expert ? weights[expert] : null);
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

  function scenarioForFocus(scen) {
    if (!scen || focusNetuid == null) return null;
    var scenarios = scen.scenarios || [];
  var match = null;
    scenarios.forEach(function (s) {
      if (!s || match) return;
      var features = s.features || {};
      var n = features.netuid != null ? Number(features.netuid) : (features.subnet_id != null ? Number(features.subnet_id) : null);
      if (n === focusNetuid) match = s;
    });
    if (match) return match;
    if (scen.regime) return { regime: scen.regime };
    if (scen.stats && scen.stats.dominant_regime) return { regime: scen.stats.dominant_regime };
    return null;
  }

  function postmortemForFocus(pm) {
    if (!pm || focusNetuid == null) return null;
    var posts = pm.postmortems;
    if (Array.isArray(posts)) {
      for (var i = 0; i < posts.length; i++) {
        var p = posts[i];
        var pred = (p && p.prediction) || {};
        if (pred.netuid != null && Number(pred.netuid) === focusNetuid) return p;
      }
      return posts[0] || null;
    }
    if (posts && typeof posts === 'object') {
      var keys = Object.keys(posts);
      for (var j = 0; j < keys.length; j++) {
        var list = posts[keys[j]] || [];
        for (var k = 0; k < list.length; k++) {
          var item = list[k];
          var pr = (item && item.prediction) || {};
          if (pr.netuid != null && Number(pr.netuid) === focusNetuid) return item;
        }
      }
    }
    return null;
  }

  function loadChips() {
    var chips = [];
    return Promise.all([
      fetchJson('/api/scenario-memory', 8000).catch(function () { return null; }),
      fetchJson('/api/ruggers/subnet/' + focusNetuid, 8000).catch(function () { return null; }),
      fetchJson('/api/postmortems?limit=20', 8000).catch(function () { return null; }),
    ]).then(function (res) {
      var scen = scenarioForFocus(res[0]);
      if (scen && scen.regime) {
        chips.push({ label: 'Regime: ' + scen.regime, tone: 'neutral' });
      } else if (scen && scen.outcome) {
        chips.push({ label: 'Scenario: ' + scen.outcome, tone: scen.outcome === 'correct' ? 'neutral' : 'warn' });
      }
      var rug = res[1];
      if (rug && rug.risk_level) {
        chips.push({ label: 'Rug risk: ' + rug.risk_level, tone: rug.risk_level === 'high' ? 'warn' : 'neutral' });
      }
      var pm = postmortemForFocus(res[2]);
      if (pm) {
        chips.push({ label: 'Autopsy: ' + (pm.judge || pm.title || 'focus SN'), tone: 'muted' });
      }
      renderChips(chips);
    });
  }

  var CACHE_TTL_MS = 60000;

  function cacheFresh(cache) {
    return cache && cache.at && (Date.now() - cache.at) < CACHE_TTL_MS;
  }

  function dailyPickPromise() {
    var cache = window.HomeHydrateCache;
    if (cacheFresh(cache) && cache.dailyPick) {
      return Promise.resolve(cache.dailyPick);
    }
    return fetchJson('/api/daily-pick', 8000).catch(function () { return {}; });
  }

  function refreshFocus() {
    if (focusNetuid == null) return Promise.resolve();
    var action = 'HOLD';
    var trailPromise = cachedTrail
      ? Promise.resolve({ trail: cachedTrail })
      : fetchJson('/api/mindmap/trail?limit=40', 10000).catch(function () { return { trail: [] }; });
    return Promise.all([
      fetchJson('/api/judges/' + focusNetuid, 15000),
      fetchJson('/api/calibration/status', 8000).catch(function () { return {}; }),
      trailPromise,
      dailyPickPromise(),
      fetchJson('/api/pick-explain/' + focusNetuid, 10000).catch(function () { return {}; }),
    ]).then(function (res) {
      var judges = res[0];
      var cal = res[1];
      var trail = (res[2] && res[2].trail) || [];
      var dp = res[3] || {};
      var explain = res[4] || {};
      action = String(dp.action || 'HOLD').toUpperCase();
      var weights = calibrationWeights(cal);
      renderJudges(judges, action, weights, explain);
      renderLearnStrip(trail, weights);
      return loadChips();
    });
  }

  function bootstrapFromCache(cache) {
    if (!cache) return null;
    var dp = cache.dailyPick || {};
    var simi = cache.simivision || {};
    var top = (simi.data && simi.data.top) || simi.top || [];
    var paramFocus = parseFocusParam();
    var n = paramFocus != null ? paramFocus : pickFocusNetuid(dp);
    if (n == null && top.length && top[0].netuid != null) {
      n = Number(top[0].netuid);
      audited = false;
    }
    if (cache.trail) cachedTrail = cache.trail;
    return { dp: dp, top: top, n: n };
  }

  function coldBootstrap() {
    Promise.all([
      dailyPickPromise(),
      fetchJson('/api/simivision', 12000).catch(function () { return {}; }),
    ]).then(function (res) {
      var dp = res[0] || {};
      var simi = res[1] || {};
      var top = (simi.data && simi.data.top) || simi.top || [];
      var paramFocus = parseFocusParam();
      var n = paramFocus != null ? paramFocus : pickFocusNetuid(dp);
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
      scrollToFocus();
      return refreshFocus();
    }).catch(function () {
      if (bodyEl) bodyEl.innerHTML = '<p class="living-focus__empty">Living Focus unavailable.</p>';
    });
  }

  function init() {
    var cache = window.HomeHydrateCache;
    var cached = bootstrapFromCache(cache);
    if (cached && cached.n != null) {
      var sn = (cached.dp.pick && cached.dp.pick.subnet) || (cached.dp.candidate && cached.dp.candidate.subnet) || cached.top[0] || {};
      setFocus(cached.n, subnetName(sn, cached.n));
      renderSwitcher(cached.top);
      scrollToFocus();
      return refreshFocus();
    }

    var waited = false;
    var timer = setTimeout(function () {
      if (waited || focusNetuid != null) return;
      waited = true;
      coldBootstrap();
    }, 2000);

    document.addEventListener('home:hydrate-cache', function onCache(ev) {
      if (waited || focusNetuid != null) return;
      waited = true;
      clearTimeout(timer);
      document.removeEventListener('home:hydrate-cache', onCache);
      var detail = ev && ev.detail;
      var boot = bootstrapFromCache(detail);
      if (!boot || boot.n == null) {
        coldBootstrap();
        return;
      }
      var sn = (boot.dp.pick && boot.dp.pick.subnet) || (boot.dp.candidate && boot.dp.candidate.subnet) || boot.top[0] || {};
      setFocus(boot.n, subnetName(sn, boot.n));
      renderSwitcher(boot.top);
      scrollToFocus();
      refreshFocus();
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
    calibrationWeights: calibrationWeights,
    trailMatchesFocus: trailMatchesFocus,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
