/* Hydrate cockpit sections from JSON APIs (homepage is a fast shell on Fly). */
(function () {
  'use strict';

  var CANONICAL_EXPERTS = ['quant', 'hype', 'dark_horse', 'technical'];

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

  function subnetNetuid(sn) {
    return sn.netuid != null ? sn.netuid : sn.id;
  }

  function subnetName(sn) {
    var name = sn.name || '';
    if (!name || /^(deprecated|unknown|none)$/i.test(name)) {
      return 'SN' + subnetNetuid(sn);
    }
    return name;
  }

  /** Registry staking_data.apy is 0–1; TaoMarketCap top-level apy is already a percent. */
  function apyPercent(sn) {
    var staking = sn.staking_data;
    if (staking && staking.apy != null) {
      var frac = Number(staking.apy);
      if (!isNaN(frac)) return frac <= 1 ? frac * 100 : frac;
    }
    if (sn.apy != null && sn.id != null) {
      var raw = Number(sn.apy);
      if (!isNaN(raw)) return raw <= 1 ? raw * 100 : raw;
    }
    return null;
  }

  function confPercent(c) {
    c = Number(c) || 0;
    return c <= 1 ? c * 100 : c;
  }

  function undervaluedScore(sn) {
    var apy = apyPercent(sn);
    if (apy == null) return null;
    var chg = Number(sn.price_change_24h) || 0;
    return apy - chg;
  }

  function undervaluedVerdict(score) {
    if (score == null || isNaN(score)) return 'UNKNOWN';
    if (score > 15) return 'DEEP VALUE';
    if (score > 5) return 'VALUE';
    if (score < 0) return 'RICH';
    return 'FAIR';
  }

  function undervaluedBadgeClass(label) {
    if (label === 'DEEP VALUE') return 'badge-buy';
    if (label === 'RICH') return 'badge-sell';
    return 'badge-watch';
  }

  function confTier(conf) {
    if (typeof window !== 'undefined' && window.ConvictionTiers && window.ConvictionTiers.confTier) {
      return window.ConvictionTiers.confTier(conf);
    }
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

  function normalizeWeights(weights) {
    var w = Object.assign({}, weights || {});
    if (w.contrarian != null) {
      w.dark_horse = Math.max(Number(w.dark_horse) || 0, Number(w.contrarian) || 0);
      delete w.contrarian;
    }
    var out = {};
    CANONICAL_EXPERTS.forEach(function (name) {
      if (w[name] != null) out[name] = Number(w[name]) || 0;
    });
    return out;
  }

  function expertLabel(name) {
    if (name === 'dark_horse') return 'Dark Horse';
    if (name === 'quant') return 'Quant';
    if (name === 'hype') return 'Hype';
    if (name === 'technical') return 'Technical';
    return String(name || 'expert');
  }

  function skeletonHtml(lines) {
    var n = lines || 3;
    var html = '<div class="hydrate-skeleton" aria-hidden="true">';
    for (var i = 0; i < n; i++) {
      var cls = i === n - 1 ? 'hydrate-skeleton__line hydrate-skeleton__line--short' : 'hydrate-skeleton__line hydrate-skeleton__line--med';
      html += '<div class="' + cls + '"></div>';
    }
    html += '</div>';
    return html;
  }

  function showHydrateSkeletons() {
    ['judges-panel', 'signals-feed-root', 'cockpit-sections-root'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.querySelector('.empty')) {
        el.innerHTML = skeletonHtml(3);
      }
    });
  }

  function normalizeLearningStats(payload) {
    if (!payload) return null;
    if (payload.data && typeof payload.data === 'object') return payload.data;
    if (payload.trust_banner) return payload;
    return null;
  }

  async function loadLearningStats() {
    if (window.SimiLearning && window.SimiLearning.stats) {
      return window.SimiLearning.stats;
    }
    try {
      var payload = await fetchJsonTimeout('/api/learning/stats', 8000);
      return normalizeLearningStats(payload);
    } catch (e) {
      try {
        var metrics = await fetchJsonTimeout('/api/learning-metrics', 8000);
        return normalizeLearningStats(metrics);
      } catch (e2) {
        return null;
      }
    }
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

  function replaceSectionContent(sectionId, html, selectors) {
    var section = document.getElementById(sectionId);
    if (!section) return;
    var list = (selectors || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    for (var i = 0; i < list.length; i++) {
      var target = section.querySelector(list[i]);
      if (target) {
        target.outerHTML = html;
        return;
      }
    }
    replaceEmptyIn(sectionId, html);
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
      var apyVal = apyPercent(pick);
      var apy = apyVal != null ? fmt(apyVal, 1) : '—';
      var callLine =
        pick.call_line ||
        (pick.reasons && pick.reasons[0]) ||
        (fmtSigned(pick.price_change_24h) + ' 24h');
      return (
        '<div class="pick-card">' +
        '<div class="pick-rank">#' + esc(pick.rank || idx + 1) + '</div>' +
        '<div class="pick-name pick-name-lg">' + esc(pick.name || 'SN' + pick.netuid) + '</div>' +
        '<div class="pick-meta">SN' + esc(pick.netuid) + ' · ' + fmt(pick.emission, 2) + ' TAO/day · ' + apy + '% APY</div>' +
        '<div class="pick-row"><div class="conviction-wrap">' +
        '<div class="conviction-lbl">Conviction</div>' +
        '<div class="conviction-bar"><div class="conviction-fill ' + t.tier + '" style="width:' + t.conf + '%;"></div></div>' +
        '<div class="pred-line">' + esc(callLine) + '</div></div>' +
        '<div class="conv-ring ' + t.tier + '" style="--ring-pct:' + t.conf + ';"><div class="conv-ring-val">' + t.conf + '</div></div></div>' +
        '<div class="tags" style="margin-top:12px;"><span class="badge ' + recBadge(rec) + '">' + esc(rec) + '</span></div></div>'
      );
    }).join('');
    replaceEmptyIn('section-simivision-picks', '<div class="picks">' + cards + '</div>');
  }

  function renderDailyPick(payload) {
    var host = document.getElementById('council-stage-body');
    if (!payload) return;

    var act = String(payload.action || 'HOLD').toUpperCase();
    if (act === 'LONG') act = 'BUY';
    var pick = payload.pick;
    var cand = payload.candidate;
    var active = pick || cand;
    var sn = (active && active.subnet) || {};
    var confSrc = active || payload;
    var finalConf = confSrc.final_confidence != null ? confSrc.final_confidence : confSrc.confidence;
    var fc = confTier(finalConf != null ? finalConf : 0);
    var audit = (active && active.audit) || {};
    var concerns = (audit.concerns || []).slice(0, 4);
    var patterns = (payload.rotation_summary && payload.rotation_summary.patterns) || [];
    var topPat = patterns[0];
    var regime = payload.regime ? String(payload.regime).toUpperCase() + ' REGIME' : '';

    function actionBadges(mainAct, audited) {
      var html =
        '<div class="council-call__action">' +
        '<span class="badge ' + recBadge(mainAct) + '">' + esc(mainAct) + '</span>';
      if (audited && audit.approved) html += '<span class="hero-audit">AUDIT PASSED</span>';
      if (audited && audit.approved === false) html += '<span class="hero-audit flagged">AUDIT FLAGGED</span>';
      if (regime) html += '<span class="council-call__regime">' + esc(regime) + '</span>';
      return html + '</div>';
    }

    var html;
    if (pick && (sn.name != null || sn.netuid != null)) {
      var pred = pick.prediction || {};
      var hz = pred.horizon_hours != null ? pred.horizon_hours : 4;
      var predLine = pred.statement
        ? (esc(pred.statement.charAt(0).toUpperCase() + pred.statement.slice(1)) +
          (finalConf != null ? ' · <strong class="accent-bright">' + fc.conf + '% confidence</strong>' : ''))
        : ('Council call' +
          (finalConf != null ? ' at <strong class="accent-bright">' + fc.conf + '% confidence</strong>' : '') +
          ' · resolve within ' + hz + ' hours');
      var reasons = (pick.reasons || []).slice(0, 3);
      var impact = pick.impact || {};
      html =
        '<div class="council-call">' +
        actionBadges(act, true) +
        '<p class="council-call__name">' + esc(sn.name || pickName(pick)) + '</p>' +
        '<p class="council-call__meta">SN' + esc(sn.netuid != null ? sn.netuid : pickNetuid(pick)) +
        ' · ' + esc(hz) + 'h resolve horizon</p>' +
        '<p class="council-call__prediction">' + predLine +
        (pick.score != null ? ' · score <b>' + fmt(pick.score, 1) + '</b>' : '') +
        '</p>' +
        (reasons.length
          ? '<ul class="council-call__reasons">' +
            reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') +
            '</ul>'
          : '') +
        (impact.summary
          ? '<p class="council-call__impact">' + esc(impact.summary) + '</p>'
          : '') +
        '<div class="council-call__conviction">' +
        '<div class="conviction-bar"><div class="conviction-fill ' + fc.tier + '" style="width:' + fc.conf + '%;"></div></div>' +
        '<span class="council-call__conf ' + fc.tier + '">' + fc.conf + '</span></div>' +
        (payload.reason ? '<p class="council-call__note">' + esc(payload.reason) + '</p>' : '') +
        (concerns.length
          ? '<ul class="council-call__concerns">' +
            concerns.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') +
            '</ul>'
          : '') +
        '</div>';
    } else {
      html =
        '<div class="council-call council-call--hold">' +
        actionBadges('HOLD', false) +
        '<p class="council-call__name">No audited long call</p>' +
        '<p class="council-call__prediction">Council stance is <strong>HOLD</strong>' +
        (payload.reason ? ' — ' + esc(payload.reason) : ' until a candidate clears the 45% audit gate.') +
        '</p>';
      if (sn.name != null || sn.netuid != null) {
        var candPred = (cand && cand.prediction) || {};
        var candReasons = ((cand && cand.reasons) || []).slice(0, 3);
        var candImpact = (cand && cand.impact) || {};
        html +=
          '<p class="council-call__candidate">Leading candidate under review: <strong>' +
          esc(sn.name || ('SN' + sn.netuid)) +
          '</strong>' +
          (sn.netuid != null ? ' (SN' + esc(sn.netuid) + ')' : '') +
          (finalConf != null ? ' · ' + fc.conf + '% confidence' : '') +
          ' <span class="council-call__candidate-tag">not published</span></p>';
        if (candPred.statement) {
          html +=
            '<p class="council-call__prediction council-call__prediction--candidate">Would-be call: ' +
            esc(candPred.statement.charAt(0).toUpperCase() + candPred.statement.slice(1)) +
            (candPred.horizon_hours != null ? ' · ' + esc(candPred.horizon_hours) + 'h horizon' : '') +
            '</p>';
        }
        if (candReasons.length) {
          html +=
            '<ul class="council-call__reasons">' +
            candReasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') +
            '</ul>';
        }
        if (candImpact.summary) {
          html += '<p class="council-call__impact">' + esc(candImpact.summary) + '</p>';
        }
        html +=
          '<div class="council-call__conviction">' +
          '<div class="conviction-bar"><div class="conviction-fill ' + fc.tier + '" style="width:' + fc.conf + '%;"></div></div>' +
          '<span class="council-call__conf ' + fc.tier + '">' + fc.conf + '</span></div>';
      }
      if (topPat) {
        html +=
          '<p class="council-call__note">Rotation lens: ' +
          esc(topPat.description || topPat.pattern || '') +
          (topPat.confidence != null
            ? ' (' + Math.round(Number(topPat.confidence) * 100) + '% pattern confidence)'
            : '') +
          '</p>';
      }
      if (concerns.length) {
        html +=
          '<ul class="council-call__concerns">' +
          concerns.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') +
          '</ul>';
      }
      html += '</div>';
    }

    if (host) host.innerHTML = html;
    else replaceEmptyIn('section-daily-pick', html);
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
      '<div class="picks">' + (hourPicks && hourPicks.length ? renderPickCards(hourPicks) : '<p class="empty">No hour picks yet.</p>') + '</div></div>' +
      '<div class="card"><div class="card-head"><h3>Day Horizon</h3><span class="src-tag">top ' + (dayPicks || []).length + ' · 24h</span></div>' +
      '<div class="picks">' + (dayPicks && dayPicks.length ? renderPickCards(dayPicks) : '<p class="empty">No day picks yet.</p>') + '</div></div></div>';
    var section = document.getElementById('section-picks');
    if (!section) return;
    var host = section.querySelector('.two-col') || section.querySelector('.card-muted');
    if (host) host.outerHTML = html;
    else replaceEmptyIn('section-picks', html);
  }

  function renderStaking(subnets) {
    if (!subnets || !subnets.length) return;
    var ranked = subnets.slice().sort(function (a, b) {
      return (apyPercent(b) || 0) - (apyPercent(a) || 0);
    }).slice(0, 5);
    var cards = ranked.map(function (sn) {
      var apy = apyPercent(sn);
      var stake = (sn.staking_data && sn.staking_data.total_stake) || sn.total_stake || sn.stake || 0;
      return (
        '<div class="metric card">' +
        '<div class="lbl">' + esc(subnetName(sn)) + '</div>' +
        '<div class="val accent-bright">' + (apy != null ? fmt(apy, 2) : '—') + '%</div>' +
        '<div class="sub">SN' + esc(subnetNetuid(sn)) + ' · stake ' + esc(stake ? String(stake) : '—') + '</div></div>'
      );
    }).join('');
    replaceSectionContent('section-staking', '<div class="mi-grid">' + cards + '</div>', '.mi-grid, .card-muted');
  }

  function renderUndervalued(subnets) {
    if (!subnets || !subnets.length) return;
    var ranked = subnets.slice().sort(function (a, b) {
      var sa = undervaluedScore(a);
      var sb = undervaluedScore(b);
      return (sb == null ? -9999 : sb) - (sa == null ? -9999 : sa);
    }).slice(0, 8);
    var rows = ranked.map(function (sn, idx) {
      var apy = apyPercent(sn);
      var chg = Number(sn.price_change_24h) || 0;
      var score = undervaluedScore(sn);
      var flag = undervaluedVerdict(score);
      return (
        '<tr><td>' + (idx + 1) + '</td>' +
        '<td class="text-primary">' + esc(subnetName(sn)) + ' <span class="pick-meta">SN' + esc(subnetNetuid(sn)) + '</span></td>' +
        '<td>' + (apy != null ? fmt(apy, 1) : '—') + '%</td>' +
        '<td class="' + (chg >= 0 ? 'text-buy' : 'text-sell') + '">' + fmtSigned(chg) + '</td>' +
        '<td>' + (score != null ? fmt(score, 1) : '—') + '</td>' +
        '<td><span class="badge ' + undervaluedBadgeClass(flag) + '">' + esc(flag) + '</span></td></tr>'
      );
    }).join('');
    var html =
      '<div class="card"><table class="tbl"><thead><tr><th>#</th><th>Subnet</th><th>APY</th><th>24h</th><th>Score</th><th>Flag</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
    replaceSectionContent('section-undervalued', html, '.card');
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
    var normalized = normalizeWeights(weights);
    var keys = CANONICAL_EXPERTS.filter(function (k) { return normalized[k] != null; });
    if (!keys.length) return;
    var maxW = Math.max.apply(null, keys.map(function (k) { return normalized[k]; })) || 1;
    var cards = keys.map(function (name) {
      var w = Number(normalized[name]) || 0;
      return (
        '<div class="expert card-soft card">' +
        '<div class="avatar">' + esc(expertLabel(name).charAt(0)) + '</div>' +
        '<div class="name">' + esc(expertLabel(name)) + '</div>' +
        '<div class="w">' + fmt(w, 3) + '</div>' +
        '<div class="wbar"><div class="wfill" style="width:' + Math.min((w / maxW) * 100, 100) + '%;"></div></div>' +
        '<span class="bias neu">LEARNED</span></div>'
      );
    }).join('');
    replaceSectionContent('section-council', '<div class="council-grid">' + cards + '</div>', '.council-grid, .card-muted');
  }

  function renderKpi(stats) {
    if (!stats) return;
    var section = document.getElementById('section-kpi');
    if (!section) return;
    var strip = section.querySelector('.kpi-strip');
    if (!strip) return;

    var tb = stats.trust_banner || {};
    var accRaw = tb.accuracy != null ? tb.accuracy : null;
    var acc = Math.round((Number(accRaw) || 0) * 1000) / 10;
    var graded = tb.graded != null ? tb.graded : (Number(stats.correct || 0) + Number(stats.wrong || 0));
    var expired = Number(stats.expired != null ? stats.expired : tb.expired || 0);
    var expiredRate = stats.expired_rate != null ? stats.expired_rate : tb.expired_rate;
    var expiredPct = expiredRate != null ? Math.round(Number(expiredRate) * 1000) / 10 : null;
    var wd = stats.watchdog || tb.watchdog || {};
    var ready = stats.brain_ui_ready != null ? stats.brain_ui_ready : tb.ready;

    var accEl = document.getElementById('kpi-accuracy');
    if (accEl) {
      accEl.textContent = graded > 0 ? acc + '%' : '—';
      accEl.className = 'val' + (acc >= 50 ? ' pos' : acc > 0 ? ' neg' : '');
    }
    var gradedEl = document.getElementById('kpi-graded');
    if (gradedEl) {
      gradedEl.textContent = (stats.correct || 0) + '✓ / ' + (stats.wrong || 0) + '✗ graded (n=' + graded + ')';
    }
    var expEl = document.getElementById('kpi-expired');
    if (expEl) {
      expEl.textContent = String(expired);
      expEl.className = 'val' + (expiredPct != null && expiredPct >= 10 ? ' neg' : '');
    }
    var expRateEl = document.getElementById('kpi-expired-rate');
    if (expRateEl) {
      expRateEl.textContent = expiredPct != null ? expiredPct + '% of ledger' : 'resolver backlog';
    }
    var pendEl = document.getElementById('kpi-pending');
    if (pendEl) pendEl.textContent = String(stats.pending || 0);
    var intEl = document.getElementById('kpi-integrity');
    if (intEl) {
      intEl.textContent = ready ? 'Ready' : 'Blocked';
      intEl.className = 'val' + (ready ? ' pos' : ' neg');
      intEl.style.fontSize = '15px';
    }
    var wdEl = document.getElementById('kpi-watchdog');
    if (wdEl) {
      if (wd.warning) {
        wdEl.textContent = wd.reason || 'watchdog warning';
      } else if (tb.message) {
        wdEl.textContent = tb.message;
      } else if (ready) {
        wdEl.textContent = 'trust surfaces unlocked';
      } else {
        wdEl.textContent = 'expired < 10% + n≥30 required';
      }
    }
  }

  function pctLabel(rate) {
    if (rate == null || isNaN(rate)) return '—';
    return (Number(rate) * 100).toFixed(1) + '%';
  }

  function renderBacktest(payload) {
    var root = document.getElementById('backtest-panel-root');
    if (!root) return;
    if (!payload || payload.status === 'empty') {
      root.innerHTML = '<p class="empty">No gradeable resolved predictions yet — backtest populates after the resolver grades picks.</p>';
      return;
    }
    if (payload.status === 'error') {
      root.innerHTML = '<p class="empty">Backtest unavailable: ' + esc(payload.error || 'error') + '</p>';
      return;
    }
    var judges = payload.judges || {};
    var council = payload.council || {};
    var html = '<div class="kpi-strip">' +
      '<div class="kpi card"><div class="lbl">Council</div><div class="v">' + pctLabel(council.win_rate) + '</div>' +
      '<div class="sub">n=' + (payload.sample_size || 0) + '</div></div>' +
      '<div class="kpi card"><div class="lbl">Oracle</div><div class="v">' + pctLabel((judges.oracle || {}).win_rate) + '</div>' +
      '<div class="sub">avg pnl ' + fmt((judges.oracle || {}).avg_pnl_pct) + '%</div></div>' +
      '<div class="kpi card"><div class="lbl">Echo</div><div class="v">' + pctLabel((judges.echo || {}).win_rate) + '</div>' +
      '<div class="sub">avg pnl ' + fmt((judges.echo || {}).avg_pnl_pct) + '%</div></div>' +
      '<div class="kpi card"><div class="lbl">Pulse</div><div class="v">' + pctLabel((judges.pulse || {}).win_rate) + '</div>' +
      '<div class="sub">avg pnl ' + fmt((judges.pulse || {}).avg_pnl_pct) + '%</div></div>' +
      '</div>';
    var history = payload.history || [];
    if (history.length) {
      html += '<table class="tbl mt-3"><thead><tr><th>Subnet</th><th>Pred</th><th>Actual</th><th>Council</th><th>Oracle</th></tr></thead><tbody>';
      history.slice(0, 8).forEach(function (row) {
        var o = (row.judges || {}).oracle || {};
        html += '<tr><td>' + esc(row.name || ('SN' + row.netuid)) + '</td>' +
          '<td class="mono">' + fmtSigned(row.predicted_pct) + '</td>' +
          '<td class="mono">' + fmtSigned(row.actual_pct) + '</td>' +
          '<td>' + (row.council_correct ? '<span class="pos">hit</span>' : '<span class="neg">miss</span>') + '</td>' +
          '<td class="mono">' + fmt(o.score, 2) + '</td></tr>';
      });
      html += '</tbody></table>';
    }
    root.innerHTML = html;
  }

  function formatDataSourceLabel(meta, subnets) {
    var primary = (meta && meta.source) || '';
    if (!primary && subnets && subnets.length) {
      var live = subnets.filter(function (sn) {
        return sn.live || String(sn.source || '').toLowerCase() === 'blockmachine';
      }).length;
      primary = live > 0 ? 'blockmachine' : (subnets[0].source || 'registry');
    }
    primary = String(primary || 'registry').toLowerCase();
    if (primary === 'blockmachine') return 'BLOCKMACHINE';
    if (primary === 'taomarketcap') return 'TAOMARKETCAP';
    if (primary === 'taostats') return 'TAOSTATS';
    return primary.toUpperCase();
  }

  function renderHero(subnets, meta) {
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
      var apy = apyPercent(sn);
      if (apy != null) {
        apySum += apy;
        apyN += 1;
      }
    });
    var sourceLabel = formatDataSourceLabel(meta, subnets);
    var sourceSub = sourceLabel === 'BLOCKMACHINE' ? 'on-chain feed' : 'live feed';
    replaceEmptyIn(
      'section-hero',
      '<div class="kpi-grid" style="grid-template-columns: repeat(6, 1fr);">' +
      '<div class="kpi-cell"><div class="k">Subnets</div><div class="v">' + subnets.length + '</div>' +
      '<div class="sub">' + gainers + ' gainers / ' + losers + ' losers</div></div>' +
      '<div class="kpi-cell"><div class="k">Avg 24h</div><div class="v">' + fmtSigned(chgSum / subnets.length) + '</div><div class="sub">24h change</div></div>' +
      '<div class="kpi-cell"><div class="k">Avg APY</div><div class="v">' + (apyN ? fmt(apySum / apyN, 2) : '—') + '%</div><div class="sub">stake yield</div></div>' +
      '<div class="kpi-cell"><div class="k">Data</div><div class="v" style="font-size:15px;">' + sourceLabel + '</div><div class="sub">' + sourceSub + '</div></div>' +
      '</div>'
    );
    document.querySelectorAll('.src-tag b').forEach(function (el) {
      el.textContent = sourceLabel;
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
      var oracle = j.oracle ? j.oracle.score.toFixed(2) : '—';
      var echo = j.echo ? j.echo.score.toFixed(2) : '—';
      var pulse = j.pulse ? j.pulse.score.toFixed(2) : '—';
      return (
        '<article class="card judge-summary" style="margin-bottom:10px;">' +
        '<div class="card-head"><h3>' + esc(j.name || ('SN' + j.netuid)) + '</h3>' +
        '<span class="badge ' + verdictClass(verdict) + '">' + esc(String(verdict).toUpperCase()) + '</span></div>' +
        '<div class="pick-meta">SN' + esc(j.netuid) + (score != null ? ' · consensus ' + Number(score).toFixed(2) : '') + '</div>' +
        '<div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-top:8px;">' +
        '<div class="kpi-cell"><div class="k">Oracle</div><div class="v">' + oracle + '</div></div>' +
        '<div class="kpi-cell"><div class="k">Echo</div><div class="v">' + echo + '</div></div>' +
        '<div class="kpi-cell"><div class="k">Pulse</div><div class="v">' + pulse + '</div></div>' +
        '</div></article>'
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
        '<td>' + confPercent(sig.confidence).toFixed(1) + '%</td></tr>';
    }).join('');
    root.innerHTML = '<table class="tbl"><thead><tr><th>Subnet</th><th>Type</th><th>Conf</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function radarPayloadFromSubnets(subnets) {
    if (!subnets || subnets.length < 3) return null;
    var ranked = subnets.slice().sort(function (a, b) {
      return (Number(b.emission) || 0) - (Number(a.emission) || 0);
    }).slice(0, 3);
    var labels = [];
    var uv = [];
    var mom = [];
    ranked.forEach(function (sn) {
      var nu = subnetNetuid(sn);
      var apy = apyPercent(sn) || 0;
      var chg = Number(sn.price_change_24h) || 0;
      labels.push('SN' + nu);
      uv.push(Math.round(Math.min(apy - chg, 100)));
      mom.push(Math.min(Math.round(50 + chg * 2), 100));
    });
    return {
      labels: labels,
      datasets: [
        { label: 'Undervalued', data: uv, color: '#00ff41' },
        { label: 'Momentum', data: mom, color: '#22d3ee' },
      ],
    };
  }

  function renderRadar(subnets) {
    var payload = radarPayloadFromSubnets(subnets);
    if (!payload) return;
    var canvas = document.getElementById('radarChart');
    if (canvas) {
      canvas.setAttribute('data-radar', JSON.stringify(payload));
      return;
    }
    var ranked = subnets.slice().sort(function (a, b) {
      return (Number(b.emission) || 0) - (Number(a.emission) || 0);
    }).slice(0, 3);
    var legend = ranked.map(function (sn) {
      var nu = subnetNetuid(sn);
      var em = Number(sn.emission) || 0;
      var chg = Number(sn.price_change_24h) || 0;
      return (
        '<div class="radar-item"><div class="name">' + esc(subnetName(sn)) + '</div>' +
        '<div class="meta">emission ' + fmt(em, 2) + ' · 24h ' + fmtSigned(chg) + '</div></div>'
      );
    }).join('');
    var html =
      '<div class="card momentum-grid"><div class="card"><div class="card-head"><h3>Subnet Radar</h3>' +
      '<span class="src-tag">top 3 · canvas</span></div><div class="chart-box"><div class="chart-canvas-wrap">' +
      '<canvas id="radarChart" data-radar="' + JSON.stringify(payload).replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '" aria-label="Subnet undervalued radar chart"></canvas>' +
      '</div></div></div><div class="card"><div class="card-head"><h3>Overlay Legend</h3></div>' +
      '<p class="section-sub section-sub--compact">Green = yield-vs-momentum undervalued score. Cyan = 24h momentum overlay.</p>' +
      legend + '</div></div>';
    replaceSectionContent('section-radar', html, '.momentum-grid, .card');
  }

  function renderIndicators(rows) {
    if (!rows || !rows.length) return;
    var cards = rows.slice(0, 6).map(function (row) {
      var os = row.oversold || {};
      var ob = row.overbought || {};
      var heat = (Number(os.count) || 0) + (Number(ob.count) || 0);
      var heatTotal = Number(os.total) || 7;
      var heatPct = Math.round((heat / (heatTotal || 7)) * 100);
      var heatClass = heatPct > 66 ? 'high' : heatPct > 33 ? 'core' : 'low';
      var sparks = row.spark_closes;
      var sparkHtml = '';
      if (sparks && sparks.length >= 2) {
        sparkHtml =
          '<div class="spark-wrap chart-canvas-wrap"><div class="spark" data-spark="' +
          esc(sparks.join(',')) + '" role="img" aria-label="Price sparkline for ' + esc(row.name || 'subnet') + '"></div></div>';
      } else {
        sparkHtml = '<div class="spark-empty" aria-hidden="true">—</div>';
      }
      var tags = '';
      if (os.convergent) tags += '<span class="badge badge-buy">OVERSOLD ' + esc(os.count) + '/' + esc(os.total) + '</span>';
      if (ob.convergent) tags += '<span class="badge badge-sell">OVERBOUGHT ' + esc(ob.count) + '/' + esc(ob.total) + '</span>';
      if (!os.convergent && !ob.convergent) tags = '<span class="badge badge-watch">NEUTRAL</span>';
      return (
        '<div class="pick-card card"><div class="ti-head"><div>' +
        '<div class="pick-name">' + esc(row.name || 'SN' + row.netuid) + '</div>' +
        '<div class="pick-meta">SN' + esc(row.netuid) + '</div></div>' + sparkHtml + '</div>' +
        '<div class="ti-heat-row vol-cluster-row"><span class="vol-cluster-label">Signal heat</span>' +
        '<div class="vol-cluster-bar-wrap"><div class="vol-cluster-bar vol-bar-' + heatClass + '" style="width:' + Math.min(heatPct, 100) + '%;"></div></div>' +
        '<span class="vol-cluster-value">' + heatPct + '%</span></div>' +
        '<div class="tags tags-tight">' + tags + '</div></div>'
      );
    }).join('');
    replaceSectionContent('section-indicators', '<div class="picks">' + cards + '</div>', '.picks, .card-muted');
  }

  function paintCharts() {
    if (typeof window.__paintSparks === 'function') window.__paintSparks();
    if (typeof window.__paintRadar === 'function') window.__paintRadar();
  }

  function renderCockpitSections(sections) {
    if (!sections || !sections.length) return;
    sections.forEach(function (card) {
      var el = document.querySelector('.cockpit-card[data-section-id="' + card.id + '"]');
      if (!el) return;
      var status = card.status || 'empty';
      el.dataset.status = status;
      var badge = el.querySelector('.cockpit-status');
      if (badge) {
        badge.textContent = status;
        badge.className = 'cockpit-status cockpit-status-' + status;
      }
      var summary = el.querySelector('.cockpit-summary');
      if (summary && card.summary) summary.textContent = card.summary;
      var metrics = el.querySelector('.cockpit-metrics');
      if (metrics && card.metrics && typeof card.metrics === 'object') {
        metrics.innerHTML = '';
        Object.keys(card.metrics).forEach(function (key) {
          var val = card.metrics[key];
          if (val == null || val === '') return;
          var row = document.createElement('div');
          row.className = 'cockpit-metric';
          row.innerHTML = '<dt>' + esc(key.replace(/_/g, ' ')) + '</dt><dd>' + esc(String(val)) + '</dd>';
          metrics.appendChild(row);
        });
      }
      var footer = el.querySelector('.cockpit-updated');
      if (footer) {
        footer.textContent = card.updated_at ? 'Updated ' + card.updated_at : 'Awaiting first scan';
      }
    });
  }

  function updateGroupData(hourPicks, dayPicks, trail, subnets) {
    var el = document.getElementById('subnet-group-data');
    if (!el) return;
    try {
      var data = JSON.parse(el.textContent);
      if (hourPicks && hourPicks.length) data.hour_picks = hourPicks;
      if (dayPicks && dayPicks.length) data.day_picks = dayPicks;
      if (trail && trail.length) data.trail = trail.slice(0, 20);
      if (subnets && subnets.length) {
        data.roster = subnets.slice(0, 24).map(function (sn) {
          return Object.assign({}, sn, { name: subnetName(sn), netuid: subnetNetuid(sn) });
        });
      }
      el.textContent = JSON.stringify(data);
      if (typeof window.__refreshSubnetGroups === 'function') window.__refreshSubnetGroups();
    } catch (e) {
      console.warn('[cockpit_hydrate] group data update failed', e);
    }
  }

  var cockpitStream = null;

  function connectCockpitStream() {
    if (cockpitStream || typeof EventSource === 'undefined') return;
    cockpitStream = new EventSource('/api/cockpit/stream');
    cockpitStream.addEventListener('cockpit.sections', function (ev) {
      try {
        var payload = JSON.parse(ev.data);
        if (payload && payload.sections) {
          renderCockpitSections(payload.sections);
        }
        document.dispatchEvent(new CustomEvent('home:cockpit-tick'));
      } catch (e) {
        console.warn('[cockpit_hydrate] SSE parse failed', e);
      }
    });
    cockpitStream.onerror = function () {
      console.warn('[cockpit_hydrate] SSE disconnect; keeping last snapshot');
    };
  }

  async function run() {
    if (document.documentElement.dataset.hydrate !== '1') return;
    showHydrateSkeletons();

    var learningPromise = loadLearningStats();
    var signalsSummaryPromise = fetchJsonTimeout('/api/signals/summary', 8000).catch(function () { return null; });
    var alertsPromise = fetchJsonTimeout('/api/alerts?refresh_checks=false', 8000).catch(function () { return null; });

    var results = await Promise.allSettled([
      fetchJsonTimeout('/api/simivision', 12000),
      fetchJsonTimeout('/api/top-picks', 25000),
      fetchJsonTimeout('/api/daily-pick', 15000),
      fetchJsonTimeout('/api/mindmap/trail?limit=20', 12000),
      learningPromise,
      fetchJsonTimeout('/api/subnets', 15000),
      fetchJsonTimeout('/api/signals?refresh=false', 15000),
      alertsPromise,
      fetchJsonTimeout('/api/cockpit/sections', 20000),
      fetchJsonTimeout('/api/indicators-convergence', 12000),
      signalsSummaryPromise,
    ]);

    var hourPicks = [];
    var dayPicks = [];
    var trail = [];
    var subnets = [];

    if (results[0].status === 'fulfilled') {
      renderSimivision((results[0].value.data || {}).top || []);
    }

    if (results[1].status === 'fulfilled') {
      hourPicks = results[1].value.hour_picks || [];
      dayPicks = results[1].value.day_picks || [];
    } else {
      try {
        var hourRes = await fetchJsonTimeout('/api/top-pick/hour', 15000);
        hourPicks = hourRes.picks || [];
        var dayRes = await fetchJsonTimeout('/api/top-pick/day', 15000);
        dayPicks = dayRes.picks || [];
      } catch (e) {
        console.warn('[cockpit_hydrate] pick fallback failed', e);
      }
    }

    if (results[2].status === 'fulfilled') renderDailyPick(results[2].value);
    renderHourDayPicks(hourPicks, dayPicks);

    if (results[3].status === 'fulfilled') {
      trail = results[3].value.trail || [];
      renderTrail(trail);
    }
    if (results[4].status === 'fulfilled' && results[4].value) {
      var stats = results[4].value;
      renderKpi(stats);
      renderCouncilWeights(stats.expert_weights || {});
      if (stats.trust_banner && window.SimiTrustBanner && window.SimiTrustBanner.render) {
        window.SimiTrustBanner.render(stats.trust_banner);
      }
    }
    if (results[5].status === 'fulfilled') {
      var subPayload = results[5].value || {};
      subnets = subPayload.subnets || [];
      renderHero(subnets, subPayload.meta || {});
      renderStaking(subnets);
      renderUndervalued(subnets);
      renderRadar(subnets);
    }
    if (results[9].status === 'fulfilled') {
      renderIndicators((results[9].value.subnets) || []);
    }
    if (results[6].status === 'fulfilled' || results[7].status === 'fulfilled' || results[10].status === 'fulfilled') {
      var sigPayload = results[6].status === 'fulfilled' ? results[6].value : {};
      var alertsPayload = results[7].status === 'fulfilled' ? results[7].value : {};
      var summaryPayload = results[10].status === 'fulfilled' ? results[10].value : null;
      if (summaryPayload && summaryPayload.total_subnets != null && typeof window.__renderSignalSummary === 'function') {
        window.__renderSignalSummary(summaryPayload);
      }
      if (typeof window.__applySignalsPayload === 'function') {
        window.__applySignalsPayload(sigPayload.signals || [], (alertsPayload.alerts) || []);
      } else {
        renderSignals(sigPayload.signals || [], (alertsPayload.alerts) || []);
      }
    }
    if (results[8].status === 'fulfilled') {
      renderCockpitSections(results[8].value.sections || []);
    }

    updateGroupData(hourPicks, dayPicks, trail, subnets);
    paintCharts();
    console.log('[cockpit_hydrate] panels updated from APIs');

    window.HomeHydrateCache = {
      dailyPick: results[2].status === 'fulfilled' ? results[2].value : null,
      simivision: results[0].status === 'fulfilled' ? results[0].value : null,
      trail: trail,
      at: Date.now(),
    };
    document.dispatchEvent(new CustomEvent('home:hydrate-cache', {
      detail: window.HomeHydrateCache,
    }));

    connectCockpitStream();

    // §27-3a: league-table /api/judges demoted off home hydrate — Living Focus uses /api/judges/{focus}.
    // Pro drawer judges panel loads via premium_judges.js when opened.
    try {
      var btRes = await fetchJsonTimeout('/api/backtest?limit=120', 12000);
      renderBacktest(btRes);
    } catch (e) {
      console.warn('[cockpit_hydrate] backtest fetch failed', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

  window.__cockpitHome = { renderHero: renderHero };
})();
