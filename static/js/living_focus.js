/** §27-3a–c + §30 Living Focus + Public Self-Update */
(function () {
  'use strict';

  var root = document.getElementById('section-living-focus');
  if (!root) return;

  var bodyEl = document.getElementById('living-focus-body');
  var learnEl = document.getElementById('living-focus-learn');
  var evidenceEl = document.getElementById('living-focus-evidence');
  var trailTeaserEl = document.getElementById('living-focus-trail-teaser');
  var shareLinkEl = document.getElementById('living-focus-share-link');
  var switcherEl = document.getElementById('living-focus-switcher');
  var ctaEl = document.getElementById('living-focus-cta');
  var subEl = document.getElementById('living-focus-sub');
  var statusChipEl = document.getElementById('living-focus-status-chip');
  var focusNetuid = null;
  var focusName = '';
  var audited = false;
  var cachedTrail = null;
  var lastLearnHtml = '';
  var lastWeightNudge = '';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function setBrainState(state) {
    if (root) root.setAttribute('data-brain-state', state || 'building');
  }

  function skeletonHtml(quietText) {
    return (
      '<div class="living-focus__skeleton" aria-hidden="true">' +
      '<p class="living-focus__judges-caption">Judges (Oracle / Echo / Pulse)</p>' +
      '<div class="living-focus__judges living-focus__judges--skeleton">' +
      '<div class="living-focus__judge"><span class="living-focus__judge-label">Oracle</span><span class="living-focus__judge-bar"></span></div>' +
      '<div class="living-focus__judge"><span class="living-focus__judge-label">Echo</span><span class="living-focus__judge-bar"></span></div>' +
      '<div class="living-focus__judge"><span class="living-focus__judge-label">Pulse</span><span class="living-focus__judge-bar"></span></div>' +
      '</div>' +
      '<p class="living-focus__quiet">' + esc(quietText || 'Building — focus loads from lane judges and graded trail.') + '</p>' +
      '</div>'
    );
  }

  function updateCtaRow() {
    if (!ctaEl) return;
    var hasFocus = focusNetuid != null;
    ctaEl.hidden = !hasFocus;
    var proveBtn = document.getElementById('living-focus-prove-btn');
    if (proveBtn) {
      proveBtn.hidden = !hasFocus;
      proveBtn.disabled = !hasFocus;
    }
    var pinBtn = document.getElementById('living-focus-pin-btn');
    if (pinBtn) {
      pinBtn.hidden = !hasFocus;
      pinBtn.disabled = !hasFocus;
      if (hasFocus && window.HabitWatchlist && window.HabitWatchlist.isPinned) {
        var pinned = window.HabitWatchlist.isPinned(focusNetuid);
        pinBtn.textContent = pinned ? 'Unpin from watchlist' : 'Pin to watchlist';
        pinBtn.dataset.pinned = pinned ? '1' : '0';
      }
    }
  }

  function dedupeBlockers(blockers) {
    var seen = {};
    return (blockers || []).filter(function (b) {
      var key = String(b || '').trim().toLowerCase();
      if (!key || seen[key]) return false;
      seen[key] = true;
      return true;
    });
  }

    if (!statusChipEl) return;
    if (!focusNetuid) {
      statusChipEl.hidden = true;
      statusChipEl.textContent = '';
      return;
    }
    statusChipEl.hidden = false;
    statusChipEl.textContent = audited ? 'Audited pick' : 'Candidate only';
  }

  function subnetName(sn, netuid) {
    if (typeof window !== 'undefined' && window.SubnetNameRegistry && window.SubnetNameRegistry.resolve) {
      return window.SubnetNameRegistry.resolve(sn, netuid);
    }
    var n = sn && (sn.name || sn.subnet_name);
    if (!n || String(n).toLowerCase() === 'none' || /^snnone$/i.test(String(n)) || /^sn\d+$/i.test(String(n).trim())) {
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
    if (bodyEl) bodyEl.innerHTML = skeletonHtml('Building focus…');
    setBrainState('building');
    updateStatusChip();
    updateCtaRow();
    root.setAttribute('data-focus-netuid', String(focusNetuid));
    window.LivingFocus = window.LivingFocus || {};
    window.LivingFocus.netuid = focusNetuid;
    window.LivingFocus.name = focusName;
    var inv = document.getElementById('inv-netuid');
    if (inv) inv.value = String(focusNetuid);
    document.dispatchEvent(new CustomEvent('living-focus:change', { detail: { netuid: focusNetuid, name: focusName } }));
    if (shareLinkEl) {
      shareLinkEl.href = '/subnet/' + focusNetuid;
      shareLinkEl.hidden = false;
    }
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

  function weightNudgeFromTrail(trail, weights) {
    var row = null;
    (trail || []).some(function (ev) {
      if (!trailMatchesFocus(ev)) return false;
      row = ev;
      return true;
    });
    if (!row) return '';
    var payload = row.payload || row;
    var expert = payload.expert || payload.signal || payload.dial || '';
    var before = payload.before;
    var after = payload.after;
    if (expert == null || before == null) return '';
    var delta = before != null && after != null ? (Number(after) - Number(before)).toFixed(2) : '';
    var dial = expert && expert.indexOf(':') >= 0 ? expert.split(':').pop() : expert;
    return (
      esc(expert) + ' weight ' +
      Number(before).toFixed(2) + ' → ' +
      (after != null ? Number(after).toFixed(2) : (weights && dial && weights[dial] != null ? Number(weights[dial]).toFixed(2) : '?')) +
      (delta ? ' (' + (Number(delta) >= 0 ? '+' : '') + delta + ')' : '')
    );
  }

  function renderWeightLean(weights, nudgeLine) {
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
    var nudge = nudgeLine
      ? '<p class="living-focus__weight-nudge">' + nudgeLine + '</p>'
      : '';
    return (
      '<div class="living-focus__weights" aria-label="Council weights">' +
      '<p class="living-focus__weights-label">Council weights · Who drives picks · <strong>' + esc(top.name) + '</strong> leads</p>' +
      rows +
      nudge +
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
    var items = dedupeBlockers(explain.blockers).slice(0, 4).map(function (b) {
      return '<li>' + esc(b) + '</li>';
    }).join('');
    return (
      '<div class="living-focus__why-not" role="status">' +
      '<p class="living-focus__why-not-title">' + esc(label) + '</p>' +
      '<ul class="living-focus__why-not-list">' + items + '</ul>' +
      '</div>'
    );
  }

  function buildLearnStripHtml(trail, weights) {
    var row = null;
    (trail || []).some(function (ev) {
      if (!trailMatchesFocus(ev)) return false;
      row = ev;
      return true;
    });
    if (!row) {
      return (
        '<div class="living-focus__learn-strip living-focus__learn-strip--empty">' +
        '<h4 class="living-focus__learn-title">Last learn</h4>' +
        '<p class="living-focus__learn-empty">No graded beat on this SN yet — appears after this call resolves.</p>' +
        '</div>'
      );
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
    return html;
  }

  function bindLearnActions(container) {
    if (!container) return;
    container.querySelectorAll('.living-focus__replay').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-prediction-id');
        if (id && window.SimiTimeCapsule && window.SimiTimeCapsule.open) {
          window.SimiTimeCapsule.open(id);
        }
      });
    });
    container.querySelectorAll('.living-focus__share').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var path = btn.getAttribute('data-share-url');
        if (path && navigator.clipboard) {
          navigator.clipboard.writeText(window.location.origin + path).catch(function () {});
        }
      });
    });
  }

  function showLearnStrip(trail, weights) {
    if (!learnEl) return;
    var html = buildLearnStripHtml(trail, weights);
    learnEl.innerHTML = html;
    learnEl.hidden = false;
    bindLearnActions(learnEl);
  }

  function renderLearnStrip(trail, weights) {
    lastLearnHtml = buildLearnStripHtml(trail, weights);
    lastWeightNudge = weightNudgeFromTrail(trail, weights);
    showLearnStrip(trail, weights);
  }

  function renderJudgesQuiet(message, trail, weights) {
    setBrainState('quiet');
    if (!bodyEl) return;
    bodyEl.innerHTML = '<p class="living-focus__empty">' + esc(message) + '</p>';
    if (trail && trail.length) {
      showLearnStrip(trail, weights || {});
    } else if (learnEl) {
      learnEl.hidden = true;
      learnEl.innerHTML = '';
    }
  }

  function renderJudges(data, action, weights, explain, trail) {
    if (!bodyEl) return;
    if (!data || data.error) {
      renderJudgesQuiet('Quiet — lane judges unavailable. Last graded beat below when trail has one.', trail, weights);
      return;
    }
    setBrainState('live');
    var consensus = data.consensus || {};
    var contested = !!consensus.contested || (consensus.agreement != null && consensus.agreement < 0.5);
    var dissent = dissentSummary(data);
    lastWeightNudge = weightNudgeFromTrail(trail, weights);
    var nudgePlain = lastWeightNudge ? esc(lastWeightNudge) : '';

    var html = '';
    if (contested) {
      html += '<p class="living-focus__contention">Council split — judges disagree on this subnet.</p>';
      if (dissent) {
        html += '<p class="living-focus__contention living-focus__contention--detail">' + esc(dissent) + '</p>';
      }
    }
    html += '<p class="living-focus__judges-caption">Lane judges (Oracle / Echo / Pulse)</p>';
    html += '<div class="living-focus__judges">' +
      judgeBar('Oracle', (data.oracle || {}).score, contested) +
      judgeBar('Echo', (data.echo || {}).score, contested) +
      judgeBar('Pulse', (data.pulse || {}).score, contested) +
      '</div>';
    html += (
      '<header class="living-focus__header">' +
      '<h3 class="living-focus__name"><a href="/subnet/' + focusNetuid + '" class="living-focus__link">' + esc(focusName) + '</a> <span class="living-focus__sn">SN' + focusNetuid + '</span></h3>' +
      '<span class="living-focus__action badge-' + (action === 'LONG' ? 'buy' : action === 'SHORT' ? 'sell' : 'watch') + '">' + esc(action || 'HOLD') + '</span>' +
      '</header>'
    );
    html += renderWeightLean(weights, nudgePlain);
    html += renderWhyNot(explain);
    if (consensus.verdict) {
      html += '<p class="living-focus__verdict">Consensus: <strong>' + esc(consensus.verdict) + '</strong>' +
        (consensus.agreement != null ? ' · agreement ' + Number(consensus.agreement).toFixed(2) : '') +
        '</p>';
    }
    bodyEl.innerHTML = html;
    showLearnStrip(trail, weights);
    updateCtaRow();
    if (ctaEl) ctaEl.hidden = false;
  }

  function renderEvidenceRows(rows) {
    if (!evidenceEl) return;
    var items = (rows || []).filter(Boolean);
    if (!items.length) {
      evidenceEl.hidden = true;
      evidenceEl.innerHTML = '';
      return;
    }
    evidenceEl.hidden = false;
    evidenceEl.innerHTML =
      '<h4 class="living-focus__evidence-title">Evidence desk</h4>' +
      '<ul class="living-focus__evidence-list">' +
      items.map(function (row) {
        return (
          '<li class="living-focus__evidence-row living-focus__evidence-row--' + esc(row.tone || 'neutral') + '">' +
          '<span class="living-focus__evidence-label">' + esc(row.label) + '</span>' +
          '<span class="living-focus__evidence-detail">' + esc(row.detail || '') + '</span>' +
          '</li>'
        );
      }).join('') +
      '</ul>';
  }

  function renderTrailTeaser(trail) {
    if (!trailTeaserEl) return;
    var rows = (trail || []).filter(trailMatchesFocus).slice(0, 3);
    if (!rows.length) {
      trailTeaserEl.hidden = true;
      trailTeaserEl.innerHTML = '';
      return;
    }
    trailTeaserEl.hidden = false;
    var html =
      '<h4 class="living-focus__trail-title">Recent brain events</h4>' +
      '<ol class="living-focus__trail-list">';
    rows.forEach(function (ev) {
      var payload = ev.payload || ev;
      var label = ev.event_type || payload.event_type || 'event';
      var note = payload.statement || payload.reason || payload.expert || '';
      html +=
        '<li><span class="living-focus__trail-type">' + esc(label) + '</span>' +
        (note ? ' · ' + esc(String(note).slice(0, 72)) : '') +
        '</li>';
    });
    html += '</ol><p class="living-focus__trail-link"><a href="#section-trail">Full learning trail →</a></p>';
    trailTeaserEl.innerHTML = html;
  }

  function renderChips(chips) {
    renderEvidenceRows(
      (chips || []).map(function (c) {
        return { label: c.label, detail: c.detail || '', tone: c.tone || 'neutral' };
      })
    );
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
        chips.push({ label: 'Scenario memory', detail: 'Regime: ' + scen.regime, tone: 'neutral' });
      } else if (scen && scen.outcome) {
        chips.push({ label: 'Scenario memory', detail: 'Outcome: ' + scen.outcome, tone: scen.outcome === 'correct' ? 'neutral' : 'warn' });
      } else if (scen && scen.name) {
        chips.push({ label: 'Scenario memory', detail: String(scen.name), tone: 'neutral' });
      }
      var rug = res[1];
      if (rug && rug.risk_level) {
        var rugDetail = rug.summary || rug.reason || ('Level ' + rug.risk_level);
        chips.push({ label: 'Rug watch', detail: rugDetail, tone: rug.risk_level === 'high' ? 'warn' : 'neutral' });
      }
      var pm = postmortemForFocus(res[2]);
      if (pm) {
        var lesson = pm.lesson || pm.summary || pm.verdict || 'graded autopsy on file';
        chips.push({ label: 'Autopsy', detail: String(lesson).slice(0, 120), tone: 'muted' });
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
      renderJudges(judges, action, weights, explain, trail);
      renderLearnStrip(trail, weights);
      renderTrailTeaser(trail);
      return loadChips();
    }).catch(function () {
      renderJudgesQuiet('Quiet — lane judges unavailable right now.', cachedTrail, {});
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
        setBrainState('quiet');
        if (top.length && top[0] && top[0].netuid != null) {
          var near = top[0];
          var nearName = subnetName(near, near.netuid);
          var nearConf = near.conviction != null ? Math.round(Number(near.conviction)) : null;
          var trigger = nearConf != null ? 'Conviction ' + nearConf + '% — watch for 45% gate.' : 'Watch weigh room for a near-call trigger.';
          if (bodyEl) {
            bodyEl.innerHTML =
              '<p class="living-focus__empty">No pinned focus — nearest near-call: <strong>' + esc(nearName) + '</strong>. ' + esc(trigger) + '</p>';
          }
        } else if (bodyEl) {
          bodyEl.innerHTML = '<p class="living-focus__empty">No focus subnet today — council has not cleared a pick.</p>';
        }
        return;
      }
      var sn = (dp.pick && dp.pick.subnet) || (dp.candidate && dp.candidate.subnet) || top[0] || {};
      setFocus(n, subnetName(sn, n));
      renderSwitcher(top);
      scrollToFocus();
      return refreshFocus();
    }).catch(function () {
      setBrainState('quiet');
      if (bodyEl) bodyEl.innerHTML = '<p class="living-focus__empty">Judges quiet — last try failed.</p>';
    });
  }

  function init() {
    if (subEl) subEl.textContent = 'Focus · Contest · Prove it · Watch us update';
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
      if (detail && detail.subnets && window.SubnetNameRegistry && window.SubnetNameRegistry.index) {
        window.SubnetNameRegistry.index(detail.subnets);
      }
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
      if (focusNetuid == null) return;
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

  var lfPinBtn = document.getElementById('living-focus-pin-btn');
  if (lfPinBtn) {
    lfPinBtn.addEventListener('click', function () {
      if (focusNetuid == null) return;
      var heroPin = document.getElementById('habit-pin-btn');
      if (heroPin && !heroPin.disabled && String(heroPin.dataset.netuid) === String(focusNetuid)) {
        heroPin.click();
        return;
      }
      if (window.HabitWatchlist && window.HabitWatchlist.togglePin) {
        window.HabitWatchlist.togglePin(focusNetuid).then(function () { updateCtaRow(); });
      }
    });
  }

  document.addEventListener('habit-watchlist:change', function () {
    updateCtaRow();
  });

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
