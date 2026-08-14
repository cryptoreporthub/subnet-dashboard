/* Hydrate cockpit sections from JSON APIs (homepage is a fast shell on Fly). */
(function () {
  'use strict';

  var CANONICAL_EXPERTS = ['quant', 'hype', 'dark_horse', 'technical'];
  var registryByNetuid = {};
  var lastDailyPickPayload = null;
  var lastSimivisionTop = null;
  var lastSimivisionMeta = null;
  var lastHourPicks = [];
  var lastDayPicks = [];

  // #region agent log
  function debugHydration(hypothesisId, message, data) {
    try {
      fetch('/__debug/hydration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hypothesisId: hypothesisId,
          location: 'static/js/cockpit_hydrate.js',
          message: message,
          data: data || {},
        }),
        keepalive: true,
      }).catch(function () {});
    } catch (e) {}
  }
  // #endregion

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function clearShellWarming() {
    var stage = document.getElementById('section-daily-pick');
    if (stage) stage.removeAttribute('data-shell-warming');
    var banner = document.getElementById('council-warming-composite');
    if (banner) banner.hidden = true;
  }

  function clearHydrateFlag() {
    if (document.documentElement.dataset.hydrate === '1') {
      document.documentElement.dataset.hydrate = '0';
    }
  }

  function maybeClearShellWarmingEarly() {
    if (
      document.getElementById('tribunal-hero') ||
      document.getElementById('k3-claim') ||
      document.querySelector('#k3-dossier #k3-claim-identity:not([hidden])')
    ) {
      clearShellWarming();
    }
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

  function isBadSubnetName(name) {
    if (!name) return true;
    var s = String(name).trim();
    return /^(deprecated|unknown|none|snnone)$/i.test(s) || /^snnone/i.test(s) || /^sn\d+$/i.test(s);
  }

  function indexRegistry(subnets) {
    registryByNetuid = {};
    (subnets || []).forEach(function (sn) {
      var nu = subnetNetuid(sn);
      if (nu != null) registryByNetuid[Number(nu)] = sn;
    });
    if (typeof window !== 'undefined') {
      window.SubnetNameRegistry = {
        byNetuid: registryByNetuid,
        index: indexRegistry,
        resolve: resolveSubnetDisplayName,
      };
    }
    refreshRegistryDependentPanels();
  }

  function resolveSubnetDisplayName(sn, netuid) {
    var nu = netuid != null ? netuid : subnetNetuid(sn || {});
    var row = registryByNetuid[Number(nu)];
    if (row) return subnetName(row);
    return subnetName(Object.assign({}, sn || {}, { netuid: nu }));
  }

  function refreshRegistryDependentPanels() {
    if (lastDailyPickPayload) renderDailyPick(lastDailyPickPayload);
    if (lastSimivisionTop) renderSimivision(lastSimivisionTop, lastSimivisionMeta || {});
    if (lastHourPicks.length || lastDayPicks.length) {
      renderHourDayPicks(lastHourPicks, lastDayPicks);
    }
  }

  function subnetName(sn) {
    var nu = subnetNetuid(sn);
    var row = registryByNetuid[Number(nu)];
    if (row) {
      var regName = row.name || '';
      if (!isBadSubnetName(regName)) return regName;
    }
    var name = sn.name || '';
    if (isBadSubnetName(name)) return 'SN' + nu;
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
      if (w.dark_horse == null) {
        w.dark_horse = Number(w.contrarian) || 0;
      }
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
    if (payload.trust_banner || payload.expert_weights || payload.correct != null || payload.wrong != null) {
      return payload;
    }
    return null;
  }

  function safePayload(value) {
    return value && typeof value === 'object' ? value : {};
  }

  function markSectionFailed(sectionId, message) {
    var section = document.getElementById(sectionId);
    if (!section) return;
    var empty = section.querySelector('.empty');
    if (!empty) return;
    empty.textContent = message;
    empty.classList.add('empty--quiet');
  }

  function pickNetuidFromPayload(payload) {
    if (!payload || typeof payload !== 'object') return null;
    var pick = payload.pick || payload.candidate;
    var sn = pick && pick.subnet;
    if (sn && sn.netuid != null) return Number(sn.netuid);
    return null;
  }

  function renderFocusJudgeCard(data) {
    var panel = document.getElementById('judges-panel');
    if (!panel || !data || data.error) return;
    function escLocal(s) {
      return esc(s);
    }
    function verdictClass(v) {
      if (v === 'bullish' || v === 'long') return 'badge-buy';
      if (v === 'bearish' || v === 'short') return 'badge-sell';
      return 'badge-watch';
    }
    var verdict = (data.consensus && data.consensus.verdict) || 'neutral';
    var score = data.consensus ? data.consensus.score : null;
    var oracle = data.oracle ? data.oracle.score.toFixed(2) : '—';
    var echo = data.echo ? data.echo.score.toFixed(2) : '—';
    var pulse = data.pulse ? data.pulse.score.toFixed(2) : '—';
    var title = escLocal(data.name || ('SN' + data.netuid));
    panel.innerHTML =
      '<article class="card judge-summary" style="margin-bottom:10px;">' +
      '<div class="card-head"><h3>' + title + '</h3>' +
      '<span class="badge ' + verdictClass(verdict) + '">' + escLocal(String(verdict).toUpperCase()) + '</span></div>' +
      '<div class="pick-meta">SN' + escLocal(data.netuid) + (score != null ? ' · consensus ' + Number(score).toFixed(2) : '') + ' · Living Focus</div>' +
      '<div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-top:8px;">' +
      '<div class="kpi-cell"><div class="k">Oracle</div><div class="v">' + oracle + '</div></div>' +
      '<div class="kpi-cell"><div class="k">Echo</div><div class="v">' + echo + '</div></div>' +
      '<div class="kpi-cell"><div class="k">Pulse</div><div class="v">' + pulse + '</div></div>' +
      '</div></article>';
  }

  function prefetchFocusJudges(payload) {
    var netuid = pickNetuidFromPayload(payload);
    if (netuid == null) return;
    fetchJsonRetry('/api/judges/' + encodeURIComponent(netuid), 18000, 1)
      .then(function (data) {
        renderFocusJudgeCard(data);
      })
      .catch(function () {
        var panel = document.getElementById('judges-panel');
        if (!panel) return;
        var empty = panel.querySelector('.empty');
        if (empty) {
          empty.textContent =
            'Quiet — lane judges unavailable right now. Open this drawer again after the API responds.';
          empty.classList.add('empty--quiet');
        }
      });
  }

  async function fetchJsonRetry(url, ms, retries) {
    if (window.apiFetchJsonRetry) {
      return window.apiFetchJsonRetry(url, ms, retries == null ? 1 : retries);
    }
    retries = retries == null ? 1 : retries;
    var lastErr;
    for (var attempt = 0; attempt <= retries; attempt++) {
      try {
        return await fetchJsonTimeout(url, ms + attempt * 4000);
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error('fetch failed');
  }

  function scheduleDeferred(fn, delayMs) {
    setTimeout(fn, delayMs == null ? 2000 : delayMs);
  }

  async function loadLearningStats() {
    var cached = window.SimiLearning && window.SimiLearning.stats;
    if (cached && (cached.trust_banner || cached.correct != null || cached.wrong != null)) {
      return cached;
    }
    try {
      var payload = await fetchJsonRetry('/api/learning/stats', 28000, 2);
      return normalizeLearningStats(payload);
    } catch (e) {
      try {
        var metrics = await fetchJsonRetry('/api/learning-metrics', 20000, 1);
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

  function ratePercent(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    if (!isFinite(n)) return null;
    // Telegram proof historically returned percentage points (for example
    // 73.2), while learning stats use a 0..1 fraction. Accept both forms.
    if (Math.abs(n) <= 1) n *= 100;
    return Math.max(0, Math.min(100, Math.round(n * 10) / 10));
  }

  function pickName(pick) {
    var sn = pick.subnet || {};
    return resolveSubnetDisplayName(sn, pick.netuid != null ? pick.netuid : sn.netuid);
  }

  function pickNetuid(pick) {
    var sn = pick.subnet || {};
    return pick.netuid != null ? pick.netuid : sn.netuid;
  }

  function renderWeighingRow(pick, gapTick) {
    var t = confTier(pick.conviction || 0);
    var state = String(pick.deliberation_state || 'WEIGHING').toUpperCase();
    var stateSlug = state.toLowerCase().replace(/_/g, '-');
    var delta = parseInt(pick.conviction_delta, 10) || 0;
    var reason = pick.reason || pick.call_line || 'Council still weighing this name.';
    var name = pickName(pick);
    var nu = pickNetuid(pick);
    var deltaHtml =
      delta > 0
        ? '<p class="wr-delta wr-delta--up">▲ +' + delta + '</p>'
        : delta < 0
          ? '<p class="wr-delta wr-delta--down">▼ ' + delta + '</p>'
          : '<p class="wr-delta wr-delta--flat">· steady</p>';
    var stitch = pick.closest_to_call
      ? '<p class="wr-stitch">≈ today&apos;s call</p>'
      : '';
    var gapWhisper = pick.gap_whisper
      ? '<p class="wr-gap-whisper">' + esc(pick.gap_whisper) + '</p>'
      : '';
    var strip = pick.near_call_strip
      ? '<div class="wr-near-strip">' + esc(pick.near_call_strip) + '</div>'
      : '';
    var stitchBorder = pick.stitch_border ? ' wr-row--stitch-border' : '';
    var gapStyle =
      gapTick != null && gapTick !== ''
        ? ' --gap-tick:' + Number(gapTick) + ';'
        : '';
    var gapEl =
      gapTick != null && gapTick !== ''
        ? '<span class="conv-ring-gap-tick" style="--gap-tick:' +
          Number(gapTick) +
          ';" aria-hidden="true"></span>'
        : '';
    var peelExtra = '';
    if (pick.expert_split) {
      peelExtra +=
        '<div class="wr-peel__block"><div class="wr-peel__label">Council experts</div>' +
        '<p class="wr-peel__split">' +
        esc(pick.expert_split) +
        '</p></div>';
    }
    if (pick.track_record) {
      peelExtra +=
        '<div class="wr-peel__block"><div class="wr-peel__label">Track record</div><p>' +
        esc(pick.track_record) +
        '</p></div>';
    }
    if (pick.horizon_line) {
      peelExtra +=
        '<div class="wr-peel__block"><div class="wr-peel__label">Horizon</div><p>' +
        esc(pick.horizon_line) +
        '</p></div>';
    }
    var nameLink =
      '<a class="wr-name__link" href="?netuid=' +
      esc(nu) +
      '" data-wr-netuid="' +
      esc(nu) +
      '">' +
      esc(name) +
      '</a>';
    return (
      '<article class="wr-row wr-row--' +
      esc(stateSlug) +
      (pick.closest_to_call ? ' wr-row--stitch' : '') +
      stitchBorder +
      '" data-netuid="' +
      esc(nu) +
      '" data-state="' +
      esc(state) +
      '">' +
      '<button type="button" class="wr-row__face" aria-expanded="false" aria-controls="wr-peel-' +
      esc(nu) +
      '">' +
      '<span class="wr-chip wr-chip--' +
      esc(stateSlug) +
      '">' +
      esc(state) +
      '</span>' +
      '<div class="wr-row__main"><div class="wr-name">' +
      nameLink +
      ' <span class="wr-netuid">SN' +
      esc(nu) +
      '</span></div>' +
      stitch +
      gapWhisper +
      '<p class="wr-reason">' +
      esc(reason) +
      '</p>' +
      deltaHtml +
      '</div>' +
      '<div class="conv-ring ' +
      t.tier +
      '" style="--ring-pct:' +
      t.conf +
      ';' +
      gapStyle +
      '">' +
      '<svg viewBox="0 0 46 46" aria-hidden="true">' +
      '<circle class="conv-ring-bg" cx="23" cy="23" r="20"></circle>' +
      '<circle class="conv-ring-fg" cx="23" cy="23" r="20"></circle></svg>' +
      gapEl +
      '<div class="conv-ring-val">' +
      t.conf +
      '</div></div>' +
      '<span class="wr-chevron" aria-hidden="true">›</span></button>' +
      strip +
      '<div class="wr-peel" id="wr-peel-' +
      esc(nu) +
      '" hidden>' +
      '<div class="wr-peel__block"><div class="wr-peel__label">Why not the call</div><p>' +
      esc(pick.why_not || "Has not crossed today's call threshold.") +
      '</p></div>' +
      '<div class="wr-peel__block"><div class="wr-peel__label">What would make it the call</div><p>' +
      esc(pick.trigger || 'Council alignment above the Daily Call bar.') +
      '</p></div>' +
      peelExtra +
      '<div class="wr-peel__grid">' +
      '<div><div class="wr-peel__label">Proximity</div><div class="wr-peel__val">' +
      esc(pick.proximity != null ? pick.proximity : 0) +
      '</div></div>' +
      '<div><div class="wr-peel__label">Conviction</div><div class="wr-peel__val">' +
      t.conf +
      '%</div></div>' +
      '<div><div class="wr-peel__label">TAO/day</div><div class="wr-peel__val">' +
      fmt(pick.emission, 2) +
      '</div></div>' +
      '<div><div class="wr-peel__label">APY</div><div class="wr-peel__val">' +
      (apyPercent(pick) != null ? fmt(apyPercent(pick), 1) : '—') +
      '%</div></div></div>' +
      '</div></article>'
    );
  }

  function renderSimivision(top, meta) {
    meta = meta || {};
    if (!top || !top.length) return;
    lastSimivisionTop = top;
    lastSimivisionMeta = meta;
    var section = document.getElementById('section-simivision-picks');
    if (!section) return;
    section.classList.add('weighing-room');

    var updated = document.getElementById('wr-updated');
    if (updated && meta.updated_ago) {
      updated.textContent = '· ' + meta.updated_ago;
    }
    var quiet = document.getElementById('wr-quiet');
    if (quiet) {
      if (meta.quiet_label) {
        quiet.hidden = false;
        quiet.textContent = meta.quiet_label;
      } else {
        quiet.hidden = true;
      }
    }
    var handoff = document.getElementById('wr-handoff');
    if (handoff) {
      if (meta.handoff) {
        handoff.hidden = false;
        handoff.textContent = meta.handoff;
      } else {
        handoff.hidden = true;
      }
    }

    var gapTick = meta.gap_tick_pct != null ? meta.gap_tick_pct : meta.call_conviction;
    if (gapTick != null) section.setAttribute('data-gap-tick', String(gapTick));

    var spine = document.getElementById('wr-spine');
    if (spine && meta.spine_whisper) {
      spine.textContent = meta.spine_whisper;
    }

    var near = [];
    var watching = [];
    top.forEach(function (pick) {
      var st = String(pick.deliberation_state || '').toUpperCase();
      if (st === 'NEAR-CALL') near.push(pick);
      else watching.push(pick);
    });
    var html = '';
    if (near.length) {
      html +=
        '<div class="wr-band" data-band="near"><div class="wr-band__label wr-band__label--near">NEAR A CALL</div>' +
        near.map(function (p) { return renderWeighingRow(p, gapTick); }).join('') +
        '</div>';
    }
    if (watching.length) {
      html +=
        '<div class="wr-band" data-band="watching"><div class="wr-band__label wr-band__label--watching">WATCHING</div>' +
        watching.map(function (p) { return renderWeighingRow(p, gapTick); }).join('') +
        '</div>';
    }
    var body = document.getElementById('weighing-room-body');
    if (body) {
      body.className = 'wr-body';
      body.id = 'weighing-room-body';
      body.innerHTML = html;
    } else {
      replaceEmptyIn('section-simivision-picks', '<div class="wr-body" id="weighing-room-body">' + html + '</div>');
    }
    if (section.dataset) section.dataset.wrBound = '';
    document.dispatchEvent(new CustomEvent('weighing-room-updated'));
    renderCautionCells(meta.caution_cells || []);
  }

  function renderCautionCells(cells) {
    var section = document.getElementById('section-caution-cells');
    var list = document.getElementById('caution-cells-list');
    if (!section || !list) return;
    if (!cells || !cells.length) {
      section.hidden = true;
      list.innerHTML = '';
      return;
    }
    section.hidden = false;
    list.innerHTML = cells
      .slice(0, 3)
      .map(function (cell) {
        return (
          '<li class="caution-cell" data-netuid="' +
          esc(cell.netuid) +
          '"><span class="caution-cell__tag">' +
          esc(cell.label || 'CAUTION') +
          '</span><span class="caution-cell__line">' +
          esc(cell.line || cell.name || '') +
          '</span></li>'
        );
      })
      .join('');
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (!el) return;
    if (value == null || value === '') {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = String(value);
  }

  function friendlySourceLabel(raw, meta) {
    meta = meta || {};
    if (meta.stale === true) return 'Stale';
    var eff = meta.effective_source || meta.source;
    if (eff && String(eff) !== 'none') {
      var name = String(eff).replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
      if (meta.stale === false) return 'Live · ' + name;
      return name;
    }
    var feed = meta.source ? String(meta.source) : '';
    if (feed && feed !== 'none') {
      return feed.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    }
    var s = String(raw || '').toLowerCase();
    if (s.indexOf('timeout') >= 0 || s.indexOf('fallback') >= 0) {
      return 'Snapshot';
    }
    if (!s || s === 'cache') return 'Live';
    return s.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function renderFooterStatus(opts) {
    opts = opts || {};
    var label = friendlySourceLabel(opts.dataSource, opts.meta);
    var sourceEl = document.getElementById('footer-source-label');
    var headerEl = document.getElementById('headerDataSource');
    if (sourceEl) sourceEl.textContent = label;
    if (headerEl) headerEl.textContent = label;
    function setMetric(name, value) {
      var wrap = document.querySelector('[data-footer-metric="' + name + '"]');
      var el = document.getElementById('footer-' + name + '-count');
      if (!wrap || !el) return;
      var n = Number(value) || 0;
      if (n > 0) {
        el.textContent = String(n);
        wrap.hidden = false;
      }
    }
    if (opts.subnets != null) setMetric('subnets', opts.subnets);
    if (opts.trail != null) setMetric('trail', opts.trail);
    if (opts.predictions != null) setMetric('predictions', opts.predictions);
  }

  function k3OrbScoreEl() {
    return document.getElementById('k3-orb-score') || document.querySelector('#k3-dossier .k3-orb-score');
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

  function patchK3LifecycleFromTrail(trail, payload) {
    var host = document.getElementById('k3-lifecycle-outcome');
    if (!host || !trail || !trail.length) return;
    var chain = host.querySelector('.k3-lifecycle-chain');
    if (chain && chain.children.length > 1) return;
    var pick = (payload && (payload.pick || payload.candidate)) || {};
    var sn = pick.subnet || {};
    var netuid = sn.netuid;
    if (netuid == null) return;
    var rows = (trail || []).filter(function (ev) {
      var p = ev.payload || ev;
      return p && p.netuid != null && Number(p.netuid) === Number(netuid);
    });
    if (!rows.length) return;
    var steps = [];
    rows.slice(0, 4).forEach(function (ev, idx) {
      var p = ev.payload || ev;
      var type = ev.event_type || p.event_type || 'event';
      var title = p.statement || p.reason || type.replace(/_/g, ' ');
      var detail = '';
      if (p.predicted_pct != null && p.actual_pct != null) {
        detail = 'Expected ' + Number(p.predicted_pct).toFixed(1) + '% → actual ' + Number(p.actual_pct).toFixed(1) + '%';
      } else if (p.expert) {
        detail = String(p.expert);
      }
      steps.push(
        '<li class="k3-lifecycle-step k3-lifecycle-step--done">' +
        '<span class="k3-lifecycle-label">' + esc(String(idx + 1) + ' · ' + type.replace(/_/g, ' ')) + '</span>' +
        '<span class="k3-lifecycle-title">' + esc(String(title).slice(0, 80)) + '</span>' +
        (detail ? '<span class="k3-lifecycle-detail">' + esc(detail) + '</span>' : '') +
        '</li>'
      );
    });
    if (!steps.length) return;
    host.innerHTML =
      '<div class="k3-layer-title">Council lifecycle</div>' +
      '<ol class="k3-lifecycle-chain" aria-label="Pick lifecycle path">' +
      steps.join('') +
      '</ol>';
  }

  function renderProofPumpTab(trust) {
    trust = trust || {};
    var quiet = document.getElementById('proof-pump-quiet');
    var pctEl = document.getElementById('proof-pump-pct');
    var metaEl = document.getElementById('proof-pump-meta');
    if (!quiet && !pctEl) return;
    var early = trust.early || {};
    var n = Number(trust.headline_n != null ? trust.headline_n : early.n) || 0;
    var rate = trust.headline_pct != null ? trust.headline_pct : (early.hit_rate != null ? Math.round(early.hit_rate * 100) : null);
    if (trust.ready && rate != null && n > 0) {
      if (quiet) quiet.hidden = true;
      if (pctEl) {
        pctEl.hidden = false;
        pctEl.textContent = String(rate) + '%';
      }
      if (metaEl) {
        metaEl.hidden = false;
        metaEl.textContent = n + ' graded early alerts · +2% in 1h claim';
      }
    } else {
      if (quiet) {
        quiet.hidden = false;
        quiet.textContent = trust.line || trust.message || 'Pump early hit-rate — grading +2% in 1h from WARMING UP / BUILDING entries.';
      }
      if (pctEl) pctEl.hidden = true;
      if (metaEl) metaEl.hidden = true;
    }
  }

  function syncProofBandFromTrust(tb) {
    var hero = document.getElementById('proof-band-score-hero');
    var section = document.getElementById('section-proof-band');
    if (!hero) return;
    var pctEl = document.getElementById('proof-band-pct');
    var metaEl = document.getElementById('proof-band-meta');
    var quietEl = document.getElementById('proof-band-quiet');
    if (!quietEl) {
      quietEl = hero.querySelector('.proof-band__quiet');
    }
    var ready = !!(tb && tb.ready);
    var graded = tb && tb.graded != null ? Number(tb.graded) : 0;
    var minG = tb && tb.min_graded != null ? Number(tb.min_graded) : 30;
    var accRaw = tb && tb.accuracy != null ? Number(tb.accuracy) : null;
    var accPct = accRaw != null ? Math.round(accRaw * 100) : null;

    if (section) section.setAttribute('data-brain-state', ready ? 'live' : 'building');

    if (ready && accPct != null && graded > 0) {
      if (!pctEl) {
        pctEl = document.createElement('div');
        pctEl.className = 'proof-band__pct';
        pctEl.id = 'proof-band-pct';
        hero.insertBefore(pctEl, hero.firstChild);
      }
      pctEl.hidden = false;
      pctEl.textContent = accPct + '%';
      pctEl.classList.add('proof-band__pct--ice');
      if (!metaEl) {
        metaEl = document.createElement('p');
        metaEl.className = 'proof-band__meta';
        metaEl.id = 'proof-band-meta';
        pctEl.insertAdjacentElement('afterend', metaEl);
      }
      metaEl.hidden = false;
      metaEl.textContent = graded + ' graded · published, not curated';
      if (quietEl) quietEl.hidden = true;
    } else {
      if (pctEl) {
        pctEl.hidden = true;
        pctEl.textContent = '—';
        pctEl.classList.remove('proof-band__pct--ice');
      }
      if (metaEl) metaEl.hidden = true;
      var body =
        (tb && tb.message) ? tb.message : 'Graded history appears after calls resolve.';
      if (typeof window.buildDeskEmptyState === 'function') {
        var wrap = document.createElement('div');
        wrap.innerHTML = window.buildDeskEmptyState({
          kind: 'warming',
          title: 'Track record building',
          body: body,
          progressN: graded > 0 ? graded : null,
          progressMax: graded > 0 ? minG : null,
          classExtra: 'proof-band__quiet',
          id: 'proof-band-quiet',
        });
        var fresh = wrap.firstChild;
        if (fresh) {
          if (quietEl && quietEl.parentNode) quietEl.parentNode.replaceChild(fresh, quietEl);
          else hero.appendChild(fresh);
        }
      } else if (!quietEl) {
        quietEl = document.createElement('p');
        quietEl.className = 'proof-band__quiet';
        quietEl.id = 'proof-band-quiet';
        hero.appendChild(quietEl);
        quietEl.hidden = false;
        quietEl.textContent =
          graded > 0 ? 'Building trust gate — ' + graded + '/' + minG + ' graded' : body;
      } else {
        quietEl.hidden = false;
        quietEl.textContent =
          graded > 0 ? 'Building trust gate — ' + graded + '/' + minG + ' graded' : body;
      }
    }
  }

  function syncProofBandGraded(graded) {
    /* legacy callers — prefer syncProofBandFromTrust */
    if (!graded) return;
    var meta = document.getElementById('proof-band-meta') ||
      document.querySelector('#proof-band-score-hero .proof-band__meta');
    if (!meta || meta.hidden) return;
    meta.textContent = graded + ' graded · published, not curated';
  }

  function syncProofEvidencePanels(tb, extras) {
    extras = extras || {};
    var councilVal = document.getElementById('proof-sub-council-val');
    var councilMeta = document.getElementById('proof-sub-council-meta');
    var tgVal = document.getElementById('proof-sub-telegram-val');
    var tgMeta = document.getElementById('proof-sub-telegram-meta');
    var resVal = document.getElementById('proof-sub-resolver-val');
    var resMeta = document.getElementById('proof-sub-resolver-meta');
    var loopVal = document.getElementById('proof-sub-loop-val');
    var loopMeta = document.getElementById('proof-sub-loop-meta');
    if (!councilVal) return;

    tb = tb || {};
    var ready = !!tb.ready;
    var graded = tb.graded != null ? Number(tb.graded) : 0;
    var accRaw = tb.accuracy != null ? Number(tb.accuracy) : null;
    var accPct = accRaw != null ? Math.round(accRaw * 100) : null;
    var minGraded = tb.min_graded != null ? Number(tb.min_graded) : 30;
    var councilPending = extras.council_pending != null
      ? Number(extras.council_pending)
      : (tb.council_pending != null ? Number(tb.council_pending) : 0);
    var pumpPending = extras.pump_pending != null
      ? Number(extras.pump_pending)
      : (tb.pump_pending != null ? Number(tb.pump_pending) : 0);
    var alignmentDiagnostics = Number(extras.alignment_diagnostic_events || 0);
    var missingPrice = tb.price_data_unavailable != null
      ? Number(tb.price_data_unavailable)
      : 0;
    if (ready && accPct != null && graded > 0) {
      councilVal.textContent = accPct + '%';
      if (councilMeta) {
        councilMeta.textContent = graded + ' graded picks';
        councilMeta.classList.remove('desk-empty');
      }
    } else {
      councilVal.textContent = '—';
      if (councilMeta) {
        var councilProgress = 'Published grades ' + graded + '/' + minGraded;
        if (councilPending > 0) councilProgress += ' · ' + councilPending + ' pending';
        if (missingPrice > 0) councilProgress += ' · ' + missingPrice + ' missing price';
        councilMeta.textContent = councilProgress;
        councilMeta.classList.add('desk-empty');
      }
    }

    var tgProof = extras.telegram_proof || {};
    var tgGraded = Number(tgProof.graded || 0);
    var tgPending = Number(tgProof.pending || 0);
    var tgUngradeable = Number(tgProof.ungradeable || 0);
    var tgRatePct = ratePercent(tgProof.hit_rate);
    if (tgProof.ready && tgRatePct != null && tgGraded > 0) {
      if (tgVal) tgVal.textContent = tgRatePct + '%';
      if (tgMeta) {
        tgMeta.textContent = tgGraded + ' graded calls';
        tgMeta.classList.remove('desk-empty');
      }
    } else {
      if (tgVal) tgVal.textContent = '—';
      if (tgMeta) {
        tgMeta.textContent = (tgGraded > 0 ? tgGraded + ' graded calls' : 'No graded calls yet') +
          (tgPending > 0 ? ' · ' + tgPending + ' pending' : '') +
          (tgUngradeable > 0 ? ' · ' + tgUngradeable + ' ungradeable' : '');
        tgMeta.classList.add('desk-empty');
      }
    }

    var expiredRate = tb.expired_rate != null ? Number(tb.expired_rate) : null;
    var resolvedPct =
      expiredRate != null ? Math.max(0, Math.round((1 - expiredRate) * 100)) : null;
    if (resolvedPct != null && graded > 0) {
      if (resVal) resVal.textContent = resolvedPct + '%';
      if (resMeta) {
        resMeta.textContent = 'Resolved vs expired backlog';
        resMeta.classList.remove('desk-empty');
      }
    } else {
      if (resVal) resVal.textContent = 'Waiting';
      if (resMeta) {
        resMeta.textContent = (graded > 0 ? graded + ' published grades' : 'No published grades yet') +
          (councilPending > 0 ? ' · ' + councilPending + ' council pending' : '') +
          (pumpPending > 0 ? ' · ' + pumpPending + ' pump pending' : '');
        resMeta.classList.add('desk-empty');
      }
    }

    var working = extras.working_count;
    if (working != null && Number(working) > 0) {
      if (loopVal) loopVal.textContent = String(working);
      if (loopMeta) {
        loopMeta.textContent = 'Signals with graded hit-rate';
        loopMeta.classList.remove('desk-empty');
      }
    } else if (graded > 0) {
      if (loopVal) loopVal.textContent = String(graded);
      if (loopMeta) {
        loopMeta.textContent = 'Graded picks in ledger';
        loopMeta.classList.remove('desk-empty');
      }
    } else {
      if (loopVal) loopVal.textContent = 'Building';
      if (loopMeta) {
        loopMeta.textContent = graded > 0
          ? graded + ' graded outcomes; outcome-backed learning is building'
          : 'No outcome-backed council learning yet' +
            (alignmentDiagnostics > 0 ? ' · ' + alignmentDiagnostics + ' diagnostic events' : '');
        loopMeta.classList.add('desk-empty');
      }
    }
  }

  function formatExpertLabel(name) {
    if (!name || name === 'unknown') return 'Unknown';
    return String(name)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  // ponytail: hide ledger hit % on homepage until sample is worth advertising
  var LEDGER_HIT_RATE_PUBLIC_MIN = 0.3;

  function ledgerMetricsPublic(block) {
    if (!block || !block.data_available) return false;
    var rate = block.hit_rate_30d;
    if (rate == null || Number(rate) < LEDGER_HIT_RATE_PUBLIC_MIN) return false;
    var aq = block.attribution_quality || {};
    if (aq.unknown_pct != null && Number(aq.unknown_pct) > 0.5) return false;
    return true;
  }

  function syncAccuracyLiftPanel(block) {
    var summary = document.getElementById('accuracy-lift-summary');
    var expertsEl = document.getElementById('accuracy-lift-experts');
    var noteEl = document.getElementById('accuracy-lift-note');
    if (!summary) return;

    block = block || {};
    var pub = block.published_only;
    var usePublished = pub && pub.data_available && Number(pub.graded_30d) > 0;
    var display = usePublished ? pub : block;

    if (!block.data_available || !block.graded_30d) {
      summary.textContent = block.note || 'Building graded history';
      summary.classList.add('desk-empty');
      if (expertsEl) {
        expertsEl.hidden = true;
        expertsEl.innerHTML = '';
      }
      if (noteEl) noteEl.textContent = '';
      return;
    }

    var graded = Number(display.graded_30d);
    var showMetrics = ledgerMetricsPublic(display);
    var line = usePublished
      ? graded + ' published council graded (30d)'
      : graded + ' graded in measurement ledger (30d)';
    if (showMetrics && display.hit_rate_30d != null) {
      line += ' · ' + Math.round(Number(display.hit_rate_30d) * 100) + '% direction hit';
    } else {
      line += ' · hit rates hidden until sample clears';
    }
    summary.textContent = line;
    summary.classList.remove('desk-empty');

    var byExpert = display.by_expert || {};
    var rows = Object.keys(byExpert)
      .map(function (key) {
        return { key: key, row: byExpert[key] };
      })
      .filter(function (entry) {
        return (
          entry.key !== 'unknown' &&
          entry.row &&
          Number(entry.row.graded) > 0
        );
      })
      .sort(function (a, b) {
        return Number(b.row.graded) - Number(a.row.graded);
      });

    if (expertsEl) {
      if (!rows.length) {
        expertsEl.hidden = true;
        expertsEl.innerHTML = '';
      } else {
        expertsEl.hidden = false;
        expertsEl.innerHTML = rows
          .map(function (entry) {
            var label = formatExpertLabel(entry.key);
            var detail = entry.row.graded + ' graded';
            if (showMetrics && entry.row.hit_rate != null) {
              detail +=
                ' · ' + Math.round(Number(entry.row.hit_rate) * 100) + '%';
            }
            return (
              '<li><span class="accuracy-lift-panel__expert">' +
              esc(label) +
              '</span> · ' +
              detail +
              '</li>'
            );
          })
          .join('');
      }
    }

    if (noteEl) {
      noteEl.textContent = usePublished
        ? 'Published council picks only — shadows and pump-desk excluded.'
        : showMetrics
          ? block.note || 'Mixed measurement ledger (30d); see published_only when available.'
          : 'Internal measurement only — published trust uses LONG picks once sample clears.';
    }
  }

  function patchK3ConvictionRing(confPct) {
    if (confPct == null || isNaN(confPct)) return;
    var ring = document.querySelector('#k3-dossier .ring-fill');
    if (ring) {
      var circ = 389.56;
      var pct = Math.max(0, Math.min(100, Number(confPct)));
      ring.style.setProperty('--ring-offset', String(circ - (circ * pct / 100)));
    }
    var fc = confTier(confPct > 1 ? confPct / 100 : confPct);
    var orb = k3OrbScoreEl();
    if (orb && fc.conf != null) {
      var tens = Math.floor(fc.conf / 10);
      var ones = fc.conf % 10;
      orb.innerHTML =
        (tens > 0 ? '<span class="digit-tens">' + tens + '</span>' : '') +
        '<span class="digit-ones">' + ones + '</span>';
    }
    syncK3GlowTier(fc.conf);
  }

  function syncK3GlowTier(confPct, action, confState) {
    var claim = document.getElementById('k3-claim');
    if (!claim) return;
    var dossier = document.getElementById('k3-dossier');
    var state = confState || (dossier ? dossier.getAttribute('data-conf-state') : '') || '';
    var pct = confPct == null || isNaN(confPct) ? 0 : Number(confPct);
    var act = String(action || '').toUpperCase();
    // Single source of truth for tier cutoffs — keep in sync with conviction_tiers.js (75/55/35).
    var t = confTier(pct > 1 ? pct / 100 : pct);
    var cool =
      state === 'resolving' ||
      state === 'delayed' ||
      state === 'zero' ||
      act === 'HOLD' ||
      t.tier === 'tier-gold' ||
      t.tier === 'tier-red';
    claim.classList.remove('k3-claim--glow-hot', 'k3-claim--glow-cool');
    claim.classList.add(cool ? 'k3-claim--glow-cool' : 'k3-claim--glow-hot');
    claim.setAttribute('data-glow', cool ? 'cool' : 'hot');
    var label = document.getElementById('k3-orb-label');
    if (label) {
      if (state === 'resolving' || state === 'delayed') label.textContent = state === 'delayed' ? 'delayed' : 'resolving';
      else if (state === 'zero') label.textContent = 'zero';
      else if (t.tier === 'tier-cyan') label.textContent = 'high';
      else if (t.tier === 'tier-lime') label.textContent = 'mid';
      else if (t.conf > 0) label.textContent = 'low';
      else label.textContent = 'conviction';
    }
  }

  function setK3LayerTeaser(layerId, text) {
    var layer = typeof layerId === 'string' ? document.getElementById(layerId) : layerId;
    if (!layer || text == null) return;
    var teaser = layer.querySelector('.k3-layer-teaser');
    if (teaser) teaser.textContent = text;
  }

  function formatExpertWeightDisplay(w) {
    var n = Number(w) || 0;
    if (n > 0 && n <= 1) return Math.round(n * 100) + '%';
    return fmt(n, 2);
  }

  function hydrateWeighedAlternatives(shortlist) {
    if (!document.getElementById('k3-layer-deliberation')) return;
    if (shortlist && shortlist.length) return;
    fetchJsonRetry('/api/daily-pick/weighed', 22000, 2)
      .then(function (weighed) {
        patchK3WeighedAgainst((weighed && weighed.shortlist) || []);
      })
      .catch(function (e) {
        console.warn('[cockpit_hydrate] weighed shortlist fetch failed', e);
      });
  }

  function patchK3WeighedAgainst(shortlist) {
    var layer = document.getElementById('k3-layer-deliberation');
    if (!layer) return;
    if (!shortlist || !shortlist.length) {
      setK3LayerTeaser(layer, 'None yet');
      return;
    }
    setK3LayerTeaser(layer, shortlist.length + ' name' + (shortlist.length === 1 ? '' : 's'));
    var body = layer.querySelector('.k3-layer-body');
    if (!body || (body.querySelector('.k3-weighed-list') && !body.querySelector('.k3-empty'))) return;
    var gate = 45;
    var sorted = shortlist.slice().sort(function (a, b) {
      var da = Math.abs(gate - Number(a.conviction || 0));
      var db = Math.abs(gate - Number(b.conviction || 0));
      return da - db;
    });
    var seenWhy = {};
    var rows = sorted.slice(0, 8).map(function (alt, idx) {
      var nu = alt.netuid;
      var name = alt.name || resolveSubnetDisplayName(alt, nu);
      var pct =
        alt.conviction != null
          ? '<span class="k3-weighed-pct">' + esc(String(Math.round(Number(alt.conviction)))) + '%</span>'
          : '';
      var whyKey = String(alt.role || '').slice(0, 40);
      var whyText = alt.role || ('Rank #' + (idx + 1) + ' — did not clear the bar');
      if (seenWhy[whyKey]) {
        whyText = whyText + ' · alt path';
      }
      seenWhy[whyKey] = true;
      var role = '<p class="k3-weighed-why">' + esc(whyText) + '</p>';
      var flow = alt.price_change_24h != null ? Number(alt.price_change_24h).toFixed(1) + '%' : '—';
      var depth = alt.volume != null ? String(alt.volume) : '—';
      var emit = alt.emission != null ? String(alt.emission) : '—';
      var compare =
        '<p class="k3-weighed-compare" hidden>flow 24h ' + esc(flow) +
        ' · depth ' + esc(depth) +
        ' · emission ' + esc(emit) + '</p>';
      return (
        '<div class="k3-weighed-row" data-netuid="' + esc(nu) + '" role="button" tabindex="0">' +
        '<div class="k3-weighed-top"><span class="k3-weighed-name">' + esc(name) + '</span>' + pct + '</div>' +
        role + compare +
        '</div>'
      );
    }).join('');
    body.innerHTML =
      '<div class="k3-deliberation"><div class="k3-weighed-list">' + rows + '</div></div>';
    body.querySelectorAll('.k3-weighed-row').forEach(function (row) {
      row.addEventListener('click', function () {
        var cmp = row.querySelector('.k3-weighed-compare');
        if (cmp) cmp.hidden = !cmp.hidden;
        var nu = row.getAttribute('data-netuid');
        if (nu && typeof window.switchToSubnet === 'function') {
          window.switchToSubnet(nu);
        }
      });
    });
  }

  function formatWeightDelta(delta) {
    if (delta == null || isNaN(Number(delta))) {
      return '<span class="k3-judge-delta flat">—</span>';
    }
    var d = Number(delta);
    if (d > 0.001) return '<span class="k3-judge-delta up">+' + fmt(d, 2) + '</span>';
    if (d < -0.001) return '<span class="k3-judge-delta down">' + fmt(d, 2) + '</span>';
    return '<span class="k3-judge-delta flat">0.00</span>';
  }

  function renderWeightNudgeLine(deltas) {
    var el = document.getElementById('k3-weight-nudge-line');
    var viz = document.getElementById('k3-weight-nudge-viz');
    if (!el && !viz) return;
    var deltaMap = deltas && typeof deltas === 'object' ? deltas : {};
    var ranked = CANONICAL_EXPERTS.map(function (name) {
      var d = Number(deltaMap[name]);
      return { name: name, delta: isNaN(d) ? 0 : d };
    }).filter(function (row) {
      return Math.abs(row.delta) > 0.001;
    }).sort(function (a, b) {
      return Math.abs(b.delta) - Math.abs(a.delta);
    }).slice(0, 4);
    if (!ranked.length) {
      if (el) { el.hidden = true; el.textContent = ''; }
      if (viz) {
        viz.hidden = false;
        viz.setAttribute('aria-hidden', 'false');
        viz.innerHTML =
          '<div class="k3-weight-nudge-viz__title">Council weights</div>' +
          '<p class="k3-weight-nudge-viz__empty">No weight shift this window — bars appear when grading nudges an expert.</p>';
      }
      return;
    }
    if (el) {
      var parts = ranked.slice(0, 2).map(function (row) {
        return expertLabel(row.name) + ' ' + (row.delta > 0 ? '+' : '') + fmt(row.delta, 2);
      });
      el.textContent = 'Council weights shifted: ' + parts.join(' · ');
      el.hidden = false;
    }
    if (viz) {
      var maxAbs = Math.max.apply(null, ranked.map(function (r) { return Math.abs(r.delta); })) || 1;
      var rows = ranked.map(function (row) {
        var up = row.delta > 0;
        var pct = Math.min(48, (Math.abs(row.delta) / maxAbs) * 48);
        return (
          '<div class="k3-weight-bar-row">' +
          '<span class="k3-weight-bar-name">' + esc(expertLabel(row.name)) + '</span>' +
          '<div class="k3-weight-bar-track"><div class="k3-weight-bar-fill k3-weight-bar-fill--' + (up ? 'up' : 'down') + '" style="width:' + pct.toFixed(1) + '%"></div></div>' +
          '<span class="k3-weight-bar-delta ' + (up ? 'up' : 'down') + '">' + (up ? '+' : '') + fmt(row.delta, 2) + '</span>' +
          '</div>'
        );
      }).join('');
      viz.innerHTML = '<div class="k3-weight-nudge-viz__title">Council weights shifted</div>' + rows;
      viz.hidden = false;
      viz.setAttribute('aria-hidden', 'false');
    }
  }

  function patchK3CouncilVotes(weights, deltas) {
    var layer = document.getElementById('k3-layer-council');
    if (!layer) return;
    var normalized = normalizeWeights(weights);
    var keys = CANONICAL_EXPERTS.filter(function (k) { return normalized[k] != null; });
    if (!keys.length) return;
    var body = layer.querySelector('.k3-layer-body');
    if (!body) return;
    // Always rewrite when hydrate has live weights — empty SSR or stale judge rows.
    var deltaMap = deltas && typeof deltas === 'object' ? deltas : {};
    var html = '<div class="k3-layer-title">Expert weights</div>';
    keys.forEach(function (name) {
      var w = Number(normalized[name]) || 0;
      html +=
        '<div class="k3-judge"><span class="k3-judge-name">' + esc(expertLabel(name)) + '</span>' +
        '<span><span class="k3-judge-weight">' + formatExpertWeightDisplay(w) + '</span>' +
        formatWeightDelta(deltaMap[name]) +
        '</span></div>';
    });
    body.innerHTML = html;
    setK3LayerTeaser(layer, keys.length + ' seat' + (keys.length === 1 ? '' : 's'));
  }

  function patchDataFreshnessFromSubnetMeta(subnets, meta) {
    if (!subnets || !subnets.length) return;
    var el = document.getElementById('dataFreshnessBadge');
    if (!el) return;
    meta = meta || {};
    var stale = meta.stale === true;
    var state = stale ? 'stale' : 'live';
    el.className = 'data-freshness-badge data-freshness-' + state;
    el.textContent = stale ? 'Stale' : 'Live';
  }

  function dailyPickGeneratedAt(payload) {
    if (!payload) return null;
    var meta = payload._meta || {};
    return payload.generated_at || payload.timestamp_utc || meta.generated_at || null;
  }

  function pickIsPublishable(payload) {
    if (!payload || !payload.pick || typeof payload.pick !== 'object') return false;
    var meta = payload._meta || {};
    if (meta.stale === true) return false;
    var audit = payload.pick.audit;
    if (!audit || audit.approved !== true) return false;
    var generatedAt = dailyPickGeneratedAt(payload);
    var generatedMs = parseIsoMs(generatedAt);
    return generatedMs > 0 && generatedMs <= Date.now() && Date.now() - generatedMs <= 25 * 60 * 60 * 1000;
  }

  function parseIsoMs(iso) {
    if (!iso) return 0;
    var t = Date.parse(iso);
    return isNaN(t) ? 0 : t;
  }

  function ssrDailyPickMeta() {
    var dossier = document.getElementById('k3-dossier');
    if (!dossier) return { generatedAt: null, action: null };
    return {
      generatedAt: dossier.getAttribute('data-generated-at') || null,
      action: String(dossier.getAttribute('data-action') || '').toUpperCase() || null,
    };
  }

  function shouldApplyDailyPickPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    var status = String(payload.status || 'ok').toLowerCase();
    if (status === 'pending' || status === 'timeout' || status === 'error') return false;
    var ssr = ssrDailyPickMeta();
    var incomingAt = parseIsoMs(dailyPickGeneratedAt(payload));
    var ssrAt = parseIsoMs(ssr.generatedAt);
    if (ssrAt && incomingAt && incomingAt < ssrAt) return false;
    var act = String(payload.action || 'HOLD').toUpperCase();
    if (act === 'BUY') act = 'LONG';
    if (ssr.action === 'LONG' && act === 'HOLD' && !payload.pick && ssrAt && (!incomingAt || incomingAt <= ssrAt)) {
      return false;
    }
    return true;
  }

  function syncDailyPickSsrMeta(payload) {
    var dossier = document.getElementById('k3-dossier');
    if (!dossier || !payload) return;
    var ga = dailyPickGeneratedAt(payload);
    if (ga) dossier.setAttribute('data-generated-at', ga);
    var act = String(payload.action || 'HOLD').toUpperCase();
    if (act === 'BUY') act = 'LONG';
    dossier.setAttribute('data-action', act);
  }

  // ponytail: 30m aging / 2h stale — upgrade path: align with ring_state fresh/aging/expiring TTLs
  var K3_STALE_AGING_MS = 30 * 60 * 1000;
  var K3_STALE_STALE_MS = 2 * 60 * 60 * 1000;

  function k3StaleBadgeState(generatedAtIso) {
    var ms = parseIsoMs(generatedAtIso);
    if (!ms) return null;
    var age = Date.now() - ms;
    if (age < K3_STALE_AGING_MS) return null;
    if (age < K3_STALE_STALE_MS) {
      return { level: 'aging', text: 'Aging · ' + Math.floor(age / 60000) + 'm ago' };
    }
    var hours = Math.floor(age / 3600000);
    var label = hours >= 24 ? Math.floor(hours / 24) + 'd' : hours + 'h';
    return { level: 'stale', text: 'Stale · ' + label + ' ago' };
  }

  function patchK3StaleBadge(generatedAtIso) {
    var badge = document.getElementById('k3-stale-badge');
    if (!badge) return;
    var iso = generatedAtIso;
    if (!iso) {
      var dossier = document.getElementById('k3-dossier');
      iso = dossier ? dossier.getAttribute('data-generated-at') : null;
    }
    var state = k3StaleBadgeState(iso);
    if (!state) {
      badge.hidden = true;
      badge.textContent = '';
      badge.className = 'k3-temporal-badge k3-stale-badge';
      return;
    }
    badge.hidden = false;
    badge.textContent = state.text;
    badge.className = 'k3-temporal-badge k3-stale-badge k3-stale-badge--' + state.level;
  }

  function patchK3DegradedNote(payload) {
    var tags = payload.scenario_tags || {};
    var isDegraded = !!(payload.hold_reason || tags.fallback);
    var note = document.getElementById('k3-degraded-note');
    var claim = document.getElementById('k3-claim');
    if (!isDegraded) {
      if (note) note.hidden = true;
      if (claim) claim.classList.remove('k3-claim--degraded');
      return;
    }
    if (claim) claim.classList.add('k3-claim--degraded');
    if (!note && claim) {
      note = document.createElement('p');
      note.id = 'k3-degraded-note';
      note.className = 'pick-degraded-note pick-degraded-note--hold';
      claim.appendChild(note);
    }
    if (note) {
      note.textContent = payload.hold_reason || 'Council fallback — not a scored call';
      note.hidden = false;
    }
  }

  function patchK3Evidence(payload) {
    var layer = document.getElementById('k3-layer-evidence');
    if (!layer || !payload) return;
    var body = layer.querySelector('.k3-layer-body');
    if (!body) return;
    var pick = payload.pick || payload.candidate;
    var active = pick || {};
    var audit = active.audit || {};
    var title = document.getElementById('k3-evidence-title');
    var sn = active.subnet || {};
    if (title && (sn.name || sn.netuid != null)) {
      title.textContent = 'Why ' + resolveSubnetDisplayName(sn, sn.netuid) + ' is on the desk';
    }
    var items = [];
    (active.reasons || []).forEach(function (r) { if (r) items.push(String(r)); });
    (audit.concerns || []).forEach(function (c) { if (c) items.push(String(c)); });
    if (payload.reason) items.unshift(String(payload.reason));
    var unique = [];
    items.forEach(function (line) {
      if (unique.indexOf(line) < 0) unique.push(line);
    });
    if (!unique.length) {
      setK3LayerTeaser(layer, 'Pending');
      var emptyHtml =
        (title ? title.outerHTML : '') +
        '<div class="k3-empty"><div class="k3-empty-text">Reasons appear when the call carries signal notes.</div></div>';
      body.innerHTML = emptyHtml;
      return;
    }
    setK3LayerTeaser(layer, unique.length + ' signal' + (unique.length === 1 ? '' : 's'));
    var titleHtml = title ? title.outerHTML : '';
    var html = titleHtml;
    unique.slice(0, 5).forEach(function (line) {
      html += '<div class="k3-signal"><span class="k3-signal-name">' + esc(line) + '</span></div>';
    });
    body.innerHTML = html;
  }

  var _k3ConfResolvingTimer = null;

  function patchK3DossierFromPayload(payload) {
    if (!payload || !document.getElementById('k3-dossier')) return false;
    if (!shouldApplyDailyPickPayload(payload)) return false;
    var tribunalHero = document.getElementById('tribunal-hero');
    if (_k3ConfResolvingTimer) {
      clearTimeout(_k3ConfResolvingTimer);
      _k3ConfResolvingTimer = null;
    }
    var brief = payload.brief || {};
    var pick = payload.pick;
    var cand = payload.candidate;
    var active = pick || cand;
    var sn = (active && active.subnet) || {};
    var confSrc = active || payload;
    // Resolve a single raw confidence value with the same field priority as
    // the SSR twin's conviction_raw chain in council_stage.html, so JS and
    // SSR always classify the same payload into the same conf-state.
    var finalConf =
      confSrc.final_confidence != null
        ? confSrc.final_confidence
        : confSrc.confidence != null
        ? confSrc.confidence
        : confSrc.conviction;
    var confState;
    var fc;
    if (finalConf == null) {
      confState = 'resolving';
      fc = { tier: 'tier-gold', conf: null };
    } else if (Number(finalConf) === 0) {
      confState = 'zero';
      finalConf = 0;
      fc = confTier(0);
    } else {
      confState = 'value';
      fc = confTier(finalConf);
    }
    var dossier = document.getElementById('k3-dossier');
    if (dossier) dossier.setAttribute('data-conf-state', confState);
    if (confState === 'resolving') {
      _k3ConfResolvingTimer = setTimeout(function () {
        _k3ConfResolvingTimer = null;
        var el = document.getElementById('k3-dossier');
        if (el && el.getAttribute('data-conf-state') === 'resolving') {
          el.setAttribute('data-conf-state', 'delayed');
          if (!tribunalHero) {
            var delayedLabel = document.getElementById('k3-orb-label');
            if (delayedLabel) delayedLabel.textContent = 'delayed';
          }
        }
      }, 15000);
    }
    var actRaw = String(payload.action || 'HOLD').toUpperCase();
    if (actRaw === 'BUY') actRaw = 'LONG';
    var snLabel = sn.name || (sn.netuid != null ? 'SN' + sn.netuid : '');

    if (brief.move && actRaw === 'LONG' && !tribunalHero) {
      setText('k3-call-headline', brief.move);
      var headline = document.getElementById('k3-call-headline');
      if (headline) {
        headline.className = 'k3-call-headline k3-call-headline--' + (brief.tone || 'neutral');
      }
    } else if (snLabel && !tribunalHero) {
      var headlineEl = document.getElementById('k3-call-headline');
      if (headlineEl) {
        headlineEl.textContent = (actRaw === 'LONG' ? 'LONG' : 'HOLD') + ' · ' + snLabel;
        headlineEl.className =
          'k3-call-headline k3-call-headline--' + (actRaw === 'LONG' ? 'go' : 'hold');
      }
    }
    var claimName = document.getElementById('k3-claim-name');
    var claimMeta = document.getElementById('k3-claim-meta');
    var claimDesc = document.getElementById('k3-claim-desc');
    var claimIdentity = document.getElementById('k3-claim-identity');
    var claimHeadName = document.getElementById('k3-claim-head-name');
    if (claimHeadName && snLabel && !tribunalHero) {
      claimHeadName.textContent = snLabel;
    }
    if (!tribunalHero && typeof window.k3SyncNetuidBand === 'function') {
      window.k3SyncNetuidBand(sn.netuid);
    }
    if (claimName) {
      // Featured Call shows name in the card head; keep identity name for hydrate IDs only
      claimName.textContent = snLabel || '';
      claimName.hidden = true;
    }
    if (claimMeta) {
      if (sn.netuid != null) {
        claimMeta.textContent = 'SN' + sn.netuid + (sn.symbol ? ' · ' + sn.symbol : '');
        claimMeta.hidden = false;
      } else {
        claimMeta.hidden = true;
      }
    }
    if (claimDesc) {
      var desc = brief.subnet_desc || brief.thesis || '';
      if (!desc && payload.reason) desc = String(payload.reason);
      if (desc) {
        claimDesc.textContent = desc.length > 96 ? desc.slice(0, 93) + '…' : desc;
        claimDesc.hidden = false;
      } else {
        claimDesc.textContent = '';
        claimDesc.hidden = true;
      }
    }
    if (claimIdentity) {
      claimIdentity.hidden = !(snLabel || (claimDesc && !claimDesc.hidden));
    }
    var actionBadge = document.getElementById('k3-action-badge');
    if (actionBadge && !tribunalHero) {
      actionBadge.hidden = false;
      actionBadge.textContent = actRaw === 'LONG' ? 'LONG' : actRaw === 'SHORT' ? 'SHORT' : actRaw || 'HOLD';
      actionBadge.className =
        'k3-badge ' + (actRaw === 'LONG' ? 'buy' : actRaw === 'SHORT' ? 'sell' : 'hold');
    }
    if (!tribunalHero) {
      syncK3GlowTier(fc.conf, payload.action, confState);
    }
    var horizonBadge = document.getElementById('k3-horizon-badge');
    if (horizonBadge) {
      horizonBadge.textContent = payload.time_horizon || payload.horizon || horizonBadge.textContent || '24h';
      horizonBadge.hidden = false;
    }
    var resolveCrumb = document.getElementById('k3-resolve-crumb');
    if (resolveCrumb) {
      if (payload.resolves_in && String(payload.outcome_status || 'pending') !== 'resolved') {
        resolveCrumb.textContent =
          'Resolves in ' + payload.resolves_in + ' · ' + (payload.time_horizon || payload.horizon || '24h') + ' window';
        resolveCrumb.hidden = false;
      } else {
        resolveCrumb.textContent = '';
        resolveCrumb.hidden = true;
      }
    }
    var socialCrumb = document.getElementById('k3-social-crumb');
    if (socialCrumb) {
      if (brief.social_crumb) {
        socialCrumb.textContent = brief.social_crumb;
        socialCrumb.hidden = false;
      } else {
        socialCrumb.textContent = '';
        socialCrumb.hidden = true;
      }
    }
    setText('k3-brief-thesis', brief.thesis || '');
    setText('k3-brief-vs', brief.vs || '');
    setText('k3-brief-vs-hold', brief.vs_hold_tao || '');
    setText('k3-brief-trigger', brief.trigger || '');
    var triggerEl = document.getElementById('k3-brief-trigger');
    if (triggerEl) {
      if (brief.trigger) {
        triggerEl.hidden = false;
        var flip = brief.trigger.replace(/^Flip to LONG when /i, 'Long when ');
        triggerEl.innerHTML = '<span class="k3-brief-trigger__kicker">FLIP</span>' + esc(flip);
      } else {
        triggerEl.hidden = true;
        triggerEl.textContent = '';
      }
    }
    var driversHost = document.getElementById('k3-evidence-drivers');
    if (driversHost && brief.evidence_drivers && brief.evidence_drivers.length) {
      driversHost.innerHTML = brief.evidence_drivers.slice(0, 3).map(function (d) {
        var tag = d.tag || 'tech';
        return '<span class="k3-evidence-driver k3-evidence-driver--' + esc(tag) + '">' + esc(tag) + ' · ' + esc(d.label || '') + '</span>';
      }).join('');
      driversHost.hidden = false;
    } else if (driversHost) {
      driversHost.innerHTML =
        '<span class="k3-evidence-empty" id="k3-evidence-empty">No evidence drivers on this call yet.</span>';
      driversHost.hidden = false;
    }

    var pump = payload.pump_chip || {};
    var pumpChip = document.getElementById('k3-pump-chip');
    var pumpTrigger = document.getElementById('k3-pump-trigger');
    if (pumpChip) {
      if (pump.show) {
        pumpChip.hidden = false;
        pumpChip.textContent = pump.label || pump.tier || '';
        pumpChip.className =
          'k3-pump-chip k3-pump-chip--' + String(pump.tier || '').toLowerCase();
      } else {
        pumpChip.hidden = true;
        pumpChip.textContent = '';
        pumpChip.className = 'k3-pump-chip';
      }
    }
    if (pumpTrigger) {
      if (pump.show && pump.trigger) {
        pumpTrigger.hidden = false;
        pumpTrigger.textContent = pump.trigger;
      } else {
        pumpTrigger.hidden = true;
        pumpTrigger.textContent = '';
      }
    }

    var orb = k3OrbScoreEl();
    if (orb && !tribunalHero) {
      if (confState === 'resolving') {
        orb.innerHTML = '<span class="digit-ones">—</span>';
      } else if (fc.conf != null) {
        var tens = Math.floor(fc.conf / 10);
        var ones = fc.conf % 10;
        orb.innerHTML =
          (tens > 0 ? '<span class="digit-tens">' + tens + '</span>' : '') +
          '<span class="digit-ones">' + ones + '</span>';
      }
    }
    if (!tribunalHero) {
      patchK3ConvictionRing(fc.conf);
    }

    var pin = document.getElementById('habit-pin-btn');
    if (pin && sn.netuid != null) {
      pin.dataset.netuid = String(sn.netuid);
      pin.disabled = false;
      pin.removeAttribute('aria-disabled');
    }
    try {
      document.dispatchEvent(new CustomEvent('home-daily-call-updated'));
    } catch (e) {}
    renderStageWhyNot(sn.netuid, payload.action || 'HOLD');
    patchK3Evidence(payload);
    patchK3WeighedAgainst(payload.shortlist || []);
    patchK3DegradedNote(payload);
    syncDailyPickSsrMeta(payload);
    patchK3StaleBadge(dailyPickGeneratedAt(payload));
    return true;
  }

  function _pdTriadLegs(triad, labels, cls) {
    triad = triad || {};
    labels = labels || {};
    function leg(on, name, label, dot) {
      return (
        '<span class="' +
        (cls || 'pd-triad__leg') +
        (on ? ' ' + (cls || 'pd-triad__leg') + '--on' : '') +
        '"><i class="pd-dot ' +
        (on ? 'pd-dot--' + dot : '') +
        '"></i><b>' +
        name +
        '</b><em>' +
        esc(label) +
        '</em></span>'
      );
    }
    if (cls === 'pd-r__leg') {
      return (
        '<span class="pd-r__legs" aria-label="Triad">' +
        '<span class="pd-r__leg' +
        (triad.inflow_quiet_load ? ' pd-r__leg--on' : '') +
        '">In ' +
        esc(labels.inflow || 'WATCH') +
        '</span>' +
        '<span class="pd-r__leg' +
        (triad.buy_pressure ? ' pd-r__leg--on' : '') +
        '">Pr ' +
        esc(labels.pressure || 'FLAT') +
        '</span>' +
        '<span class="pd-r__leg' +
        (triad.price_coil ? ' pd-r__leg--on' : '') +
        '">Coil ' +
        esc(labels.coil || 'OPEN') +
        '</span></span>'
      );
    }
    return (
      '<div class="pd-triad" aria-label="Pre-pump triad">' +
      leg(!!triad.inflow_quiet_load, 'Inflow', labels.inflow || 'WATCH', 'in') +
      leg(!!triad.buy_pressure, 'Pressure', labels.pressure || 'FLAT', 'pr') +
      leg(!!triad.price_coil, 'Coil', labels.coil || 'OPEN', 'coil') +
      '</div>'
    );
  }

  function isPumpScanMode() {
    return !!document.querySelector('[data-pump-scan="1"]');
  }

  /** One cyan line: last ≤5 legs (↑ +4% (2h) → …) plus optional match %. */
  function pumpPatternLineHtml(row, classExtra) {
    if (!row || row.timing === 'exit') return '';
    var strip = row.direction_strip || row.pattern_label;
    if (!strip) return '';
    if (!row.direction_strip && row.pattern_class === 'insufficient_data') return '';
    var suffix = '';
    var prob =
      row.re_pump_prob != null && !isNaN(Number(row.re_pump_prob))
        ? Number(row.re_pump_prob)
        : null;
    if (prob != null && prob > 0) {
      suffix = ' · ' + Math.round(prob * 100) + '%';
    } else if (
      row.pattern_confidence != null &&
      !isNaN(Number(row.pattern_confidence)) &&
      Number(row.pattern_confidence) >= 0.5
    ) {
      suffix = ' · ' + Math.round(Number(row.pattern_confidence) * 100) + '%';
    }
    var title = row.pattern_class ? esc(row.pattern_class) : 'Direction path';
    var cls = 'pump-pattern-line' + (classExtra ? ' ' + classExtra : '');
    return (
      '<div class="pump-pattern-rail"><p class="' +
      cls +
      '" title="' +
      title +
      '">' +
      esc(strip) +
      suffix +
      '</p></div>'
    );
  }

  function renderPumpScanMetaWrap(trust, early, live, exitN) {
    var wrap = document.getElementById('pd-meta-wrap');
    if (!wrap) return;
    var census =
      '<div class="pds-census" id="pd-census" aria-label="Desk census">' +
      '<span class="pds-census__chip pds-census__chip--lead"><b id="pd-census-lead">' +
      early +
      '</b> lead</span>' +
      '<span class="pds-census__chip pds-census__chip--live"><b id="pd-census-live">' +
      live +
      '</b> live</span>' +
      '<span class="pds-census__chip pds-census__chip--exit"><b id="pd-census-exit">' +
      exitN +
      '</b> exit</span></div>';
    if (trust && trust.ready && trust.headline_pct != null) {
      var n = trust.headline_n != null ? trust.headline_n : (trust.early && trust.early.n) || 0;
      wrap.innerHTML =
        '<div class="pds-proof__ready">' +
        '<span class="pds-proof__pct">' +
        esc(trust.headline_pct) +
        '%</span>' +
        '<span class="pds-proof__copy">hit +2% in 1h · n=' +
        esc(n) +
        '</span></div>' +
        census;
    } else {
      var line =
        (trust && trust.line) || 'Early alerts: grading starts once lead phase entries resolve (1h).';
      wrap.innerHTML =
        '<p class="pds-proof__line pds-proof__line--building" id="pump-alert-trust">' +
        esc(line) +
        '</p>' +
        census;
    }
  }

  function buildPumpHeroVisual(phase, progress) {
    var phaseSlug = String(phase || 'STIRRING').toLowerCase();
    var arc = '';
    var pts = Array.isArray(progress)
      ? progress
          .map(function (v) {
            return Number(v);
          })
          .filter(function (n) {
            return !isNaN(n);
          })
      : [];
    if (pts.length >= 2) {
      var lo = Math.min.apply(null, pts);
      var hi = Math.max.apply(null, pts);
      var span = hi - lo;
      var arcPct = Math.min(92, Math.max(28, Math.round((span / Math.max(hi, 1)) * 100 + 20)));
      arc =
        '<svg class="pds-hero__arc" viewBox="0 0 120 72" aria-hidden="true">' +
        '<path class="pds-hero__arc-track" d="M8 64 A52 52 0 0 1 112 64" fill="none"/>' +
        '<path class="pds-hero__arc-fill" d="M8 64 A52 52 0 0 1 112 64" fill="none" pathLength="100" stroke-dasharray="' +
        arcPct +
        ' 100"/></svg>';
    }
    return (
      '<div class="pds-hero__visual pds-hero__visual--' +
      esc(phaseSlug) +
      '" data-slot="hero-visual">' +
      arc +
      '</div>'
    );
  }

  function renderPumpScanHeroCard(row) {
    if (!row || row.netuid == null) return '';
    var triad = row.triad || {};
    var labels = row.triad_labels || {};
    var score = row.score != null ? Number(row.score) : 0;
    var trigger = row.trigger_score != null ? Number(row.trigger_score) : 0.72;
    var trigPct = Math.min(100, Math.round((score / trigger) * 100));
    var formPct =
      row.formation_pct != null ? Number(row.formation_pct) : Math.min(100, Math.round(score * 100));
    var confirmPct =
      row.confirm_pct != null
        ? Number(row.confirm_pct)
        : row.momentum_pct != null
          ? Number(row.momentum_pct)
          : formPct;
    var timing = String(row.timing || 'lead');
    var badgeSlug = String(row.badge || '')
      .toLowerCase()
      .replace(/\s+/g, '-');
    var phase = String(row.phase || 'STIRRING').toUpperCase();
    var order = [
      ['STIRRING', 'Stir'],
      ['ACCUMULATING', 'Build'],
      ['PUMPING', 'Pump'],
      ['COOLING', 'Cool'],
    ];
    var phaseHtml = order
      .map(function (pair) {
        return (
          '<li class="pds-phase__step' +
          (phase === pair[0] ? ' pds-phase__step--now' : '') +
          '">' +
          pair[1] +
          '</li>'
        );
      })
      .join('');
    var progress = Array.isArray(row.progress_series) ? row.progress_series : [];
    var sparkHtml =
      progress.length >= 2
        ? '<span class="pds-hero__spark"><span class="pump-progress" data-progress="' +
          esc(progress.join(',')) +
          '" role="img" aria-label="Score trend"></span></span>'
        : '';
    var thesis = row.thesis || '';
    var triggerCopy = row.trigger || row.subtitle || '';
    var patternLine = pumpPatternLineHtml(row, 'pump-pattern-line--hero');
    return (
      '<article class="pds-hero pds-hero--' +
      esc(timing) +
      ' pump-hero__card" id="pump-desk-hero" data-netuid="' +
      esc(row.netuid) +
      '" data-name="' +
      esc(pumpRowDisplayName(row)) +
      '">' +
      '<div class="pds-hero__stage">' +
      buildPumpHeroVisual(phase, progress) +
      '<div class="pds-hero__copy">' +
      '<div class="pds-hero__top">' +
      '<span class="pds-hero__badge pds-hero__badge--' +
      esc(badgeSlug) +
      '">' +
      esc(row.badge || '') +
      '</span>' +
      '<a class="pds-hero__name" href="/subnet/' +
      esc(row.netuid) +
      '">' +
      esc(pumpRowDisplayName(row)) +
      ' <b>SN' +
      esc(row.netuid) +
      '</b></a>' +
      (row.updated_ago ? '<span class="pds-hero__ago">' + esc(row.updated_ago) + '</span>' : '') +
      '</div>' +
      patternLine +
      '<div class="pds-hero__headline" aria-label="' +
      trigPct +
      ' percent to trigger"><span class="pds-hero__pct">' +
      trigPct +
      '<i>%</i></span><span class="pds-hero__pct-lbl">to trigger</span></div>' +
      '<div class="pds-hero__bar" role="progressbar" aria-valuenow="' +
      trigPct +
      '" aria-valuemin="0" aria-valuemax="100"><span class="pds-hero__bar-fill" style="width:' +
      trigPct +
      '%"></span>' +
      sparkHtml +
      '</div></div></div>' +
      '<ol class="pds-phase" aria-label="Formation phase">' +
      phaseHtml +
      '</ol>' +
      (thesis ? '<p class="pds-hero__thesis">' + esc(thesis) + '</p>' : '') +
      (triggerCopy ? '<p class="pds-hero__trigger">' + esc(triggerCopy) + '</p>' : '') +
      '<div class="pds-strip" aria-label="Metrics and triad">' +
      renderPumpMetricsBar(row, 'pds') +
      '<p class="pds-strip__triad">' +
      '<span class="pds-strip__pill' +
      (triad.inflow_quiet_load ? ' pds-strip__pill--on' : '') +
      '">In ' +
      esc(labels.inflow || 'WATCH') +
      '</span>' +
      '<span class="pds-strip__pill' +
      (triad.buy_pressure ? ' pds-strip__pill--on' : '') +
      '">Pr ' +
      esc(labels.pressure || 'FLAT') +
      '</span>' +
      '<span class="pds-strip__pill' +
      (triad.price_coil ? ' pds-strip__pill--on' : '') +
      '">Coil ' +
      esc(labels.coil || 'OPEN') +
      '</span></p></div>' +
      (row.size_line ? '<p class="pds-hero__chip">' + esc(row.size_line) + '</p>' : '') +
      (row.whale_archetype
        ? '<p class="pds-hero__chip pds-hero__chip--whale">' + esc(row.whale_archetype) + '</p>'
        : '') +
      (row.wallet_chip
        ? '<p class="pds-hero__chip pds-hero__chip--wallet">' + esc(row.wallet_chip) + '</p>'
        : '') +
      renderRugHistoryChip(row, 'pds-hero__chip') +
      (row.telegram_chip
        ? '<p class="pds-hero__chip pds-hero__chip--tg">' + esc(row.telegram_chip) + '</p>'
        : '') +
      (row.owner_chip
        ? '<p class="pds-hero__chip pds-hero__chip--owner">' + esc(row.owner_chip) + '</p>'
        : '') +
      renderAnglesBlock(row) +
      '<a class="pds-hero__cta home-cta home-cta--primary" id="pump-desk-cta" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '" data-name="' +
      esc(pumpRowDisplayName(row)) +
      '">' +
      esc(pumpDossierCtaLabel(row)) +
      '</a></article>'
    );
  }

  function renderPeersBlock(row, prefix) {
    var peers = row && row.peers;
    if (!peers || (!peers.lane && !(peers.matches && peers.matches.length))) return '';
    var cls = prefix || 'pds-peers';
    var barCls = prefix && prefix.indexOf('pd-') === 0 ? 'pd-angles' : 'pds-angles';
    var matches = Array.isArray(peers.matches) ? peers.matches : [];
    var chips = '';
    if (peers.lane) {
      chips +=
        '<span class="' + cls + '__lane" title="Pulse lane">' + esc(peers.lane) + '</span>';
    }
    if (peers.rarity != null) {
      chips +=
        '<span class="' +
        cls +
        '__rarity" title="Signature rarity">' +
        esc(peers.rarity) +
        ' rarity</span>';
    }
    var matchHtml = matches
      .slice(0, 3)
      .map(function (k) {
        var lead = leadPctOf(k);
        var shared = Array.isArray(k.shared) && k.shared.length ? k.shared.slice(0, 2).join(' · ') : '';
        return (
          '<a class="' +
          cls +
          '__match" href="/subnet/' +
          esc(k.netuid) +
          '" title="' +
          esc(lead + '% of #1' + (shared ? ' · ' + shared : k.lane ? ' · ' + k.lane : '')) +
          '"><span class="' +
          cls +
          '__match-head">' +
          esc(k.name || 'SN' + k.netuid) +
          ' <b>SN' +
          esc(k.netuid) +
          '</b>' +
          (k.lane ? ' <i>' + esc(k.lane) + '</i>' : '') +
          '</span><span class="' +
          barCls +
          '__chip-meta"><em>' +
          lead +
          '% of #1</em></span><span class="' +
          barCls +
          '__bar" role="progressbar" aria-valuenow="' +
          lead +
          '" aria-valuemin="0" aria-valuemax="100"><span class="' +
          barCls +
          '__bar-fill" style="width:' +
          lead +
          '%"></span></span></a>'
        );
      })
      .join('');
    return (
      '<section class="' +
      barCls +
      '__section ' +
      barCls +
      '__section--peers ' +
      cls +
      '" aria-label="Peers">' +
      '<header class="' +
      barCls +
      '__head ' +
      cls +
      '__meta"><h3 class="' +
      barCls +
      '__label ' +
      cls +
      '__label">Peers</h3>' +
      chips +
      '</header>' +
      (matchHtml ? '<div class="' + barCls + '__list ' + cls + '__list">' + matchHtml + '</div>' : '') +
      '</section>'
    );
  }

  function leadPctOf(k) {
    return Math.max(0, Math.min(100, Math.round(Number(k && k.to_lead_pct != null ? k.to_lead_pct : 0))));
  }

  function renderPumpMetricsBar(row, prefix) {
    if (!row) return '';
    var root = prefix || 'pds';
    var cls = root + '-metrics-bar';
    var score = row.score != null ? Number(row.score) : 0;
    var formPct =
      row.formation_pct != null ? Number(row.formation_pct) : Math.min(100, Math.round(score * 100));
    var confirmPct =
      row.confirm_pct != null
        ? Number(row.confirm_pct)
        : row.momentum_pct != null
          ? Number(row.momentum_pct)
          : formPct;
    var line1 =
      '<span>Form <b>' +
      esc(formPct) +
      '</b></span><span>Conf <b>' +
      esc(confirmPct) +
      '</b></span><span>Gap <b>' +
      esc(row.distance != null ? row.distance : '—') +
      '</b></span>';
    var line2Parts = [];
    if (row.vol_pct != null) line2Parts.push('<span>Vol <b>' + esc(row.vol_pct) + '%</b></span>');
    if (row.buy_pct != null) line2Parts.push('<span>Buys <b>' + esc(row.buy_pct) + '%</b></span>');
    return (
      '<div class="' +
      cls +
      '" aria-label="Formation metrics"><p class="' +
      cls +
      '__line">' +
      line1 +
      '</p>' +
      (line2Parts.length
        ? '<p class="' + cls + '__line">' + line2Parts.join('') + '</p>'
        : '') +
      '</div>'
    );
  }

  function renderRugHistoryChip(row, chipClass) {
    var n = row && row.owner_rug_count != null ? Number(row.owner_rug_count) : 0;
    if (!n || n <= 0) return '';
    return (
      '<p class="' +
      chipClass +
      ' ' +
      chipClass +
      '--rug-history">(Flagged in ' +
      esc(n) +
      ' recent rugs)</p>'
    );
  }

  function groupedAnglePct(g) {
    if (!g) return 0;
    if (g.pct != null) return Math.max(0, Math.min(100, Math.round(Number(g.pct))));
    if (g.to_lead_pct != null) return leadPctOf(g);
    return 0;
  }

  function renderGroupedAngleEntry(root, g) {
    if (!g) return '';
    var count = g.count != null ? Math.max(1, Math.round(Number(g.count))) : 1;
    var label = g.label || g.name || 'Match';
    var pct = groupedAnglePct(g);
    return (
      '<span class="' +
      root +
      '__grouped">' +
      esc(count) +
      '× ' +
      esc(label) +
      ' <b>[' +
      pct +
      '%]</b></span>'
    );
  }

  function angleChipHtml(root, k, opts) {
    opts = opts || {};
    var lead = leadPctOf(k);
    var extra = opts.extraLabel || '';
    var combined = !!opts.combined;
    return (
      '<a class="' +
      root +
      '__chip' +
      (combined ? ' ' + root + '__chip--combined' : '') +
      '" href="/subnet/' +
      esc(k.netuid) +
      '" title="' +
      esc(lead + '% of #1 heat' + (opts.titleSuffix ? ' · ' + opts.titleSuffix : '')) +
      '"><span class="' +
      root +
      '__chip-head">' +
      esc(k.name || 'SN' + k.netuid) +
      ' <b>SN' +
      esc(k.netuid) +
      '</b></span><span class="' +
      root +
      '__chip-meta"><i>' +
      lead +
      '% of #1' +
      (extra ? ' · ' + esc(extra) : '') +
      '</i></span><span class="' +
      root +
      '__bar" role="progressbar" aria-valuenow="' +
      lead +
      '" aria-valuemin="0" aria-valuemax="100"><span class="' +
      root +
      '__bar-fill' +
      (combined ? ' ' + root + '__bar-fill--combined' : '') +
      '" style="width:' +
      lead +
      '%"></span></span></a>'
    );
  }

  function renderAnglesBlock(row, prefix) {
    var root = prefix || 'pds-angles';
    var peerPrefix = root.indexOf('pd-') === 0 ? 'pd-peers' : 'pds-peers';
    var leadReplicas = Array.isArray(row && row.lead_replicas) ? row.lead_replicas : [];
    var correlatedPeers = Array.isArray(row && row.correlated_peers) ? row.correlated_peers : [];
    var peers = row && row.peers;
    var combined = row && row.combined;
    var hasPeerMeta =
      peers &&
      (peers.lane || peers.rarity != null);
    if (!leadReplicas.length && !correlatedPeers.length && !hasPeerMeta && !combined) return '';
    var html =
      '<div class="' +
      root +
      '" aria-label="Lead Replicas, Correlated Peers, Combined">';
    if (leadReplicas.length) {
      html +=
        '<section class="' +
        root +
        '__section ' +
        root +
        '__section--replicas"><header class="' +
        root +
        '__head"><h3 class="' +
        root +
        '__label">Lead Replicas</h3><a class="' +
        root +
        '__more" href="#pump-desk-more">View ladder</a></header><div class="' +
        root +
        '__grouped-list">';
      leadReplicas.slice(0, 3).forEach(function (g) {
        html += renderGroupedAngleEntry(root, g);
      });
      html += '</div></section>';
    }
    if (correlatedPeers.length || hasPeerMeta) {
      var peerChips = '';
      if (peers && peers.lane) {
        peerChips +=
          '<span class="' +
          peerPrefix +
          '__lane" title="Pulse lane">' +
          esc(peers.lane) +
          '</span>';
      }
      if (peers && peers.rarity != null) {
        peerChips +=
          '<span class="' +
          peerPrefix +
          '__rarity" title="Signature rarity">' +
          esc(peers.rarity) +
          ' rarity</span>';
      }
      html +=
        '<section class="' +
        root +
        '__section ' +
        root +
        '__section--peers ' +
        peerPrefix +
        '"><header class="' +
        root +
        '__head ' +
        peerPrefix +
        '__meta"><h3 class="' +
        root +
        '__label ' +
        peerPrefix +
        '__label">Correlated Peers</h3>' +
        peerChips +
        '</header>';
      if (correlatedPeers.length) {
        html += '<div class="' + root + '__grouped-list">';
        correlatedPeers.slice(0, 3).forEach(function (g) {
          html += renderGroupedAngleEntry(root, g);
        });
        html += '</div>';
      }
      html += '</section>';
    }
    if (combined && combined.netuid != null) {
      html +=
        '<section class="' +
        root +
        '__section ' +
        root +
        '__section--combined"><header class="' +
        root +
        '__head"><h3 class="' +
        root +
        '__label">Combined <em>experimental</em></h3></header><div class="' +
        root +
        '__list">' +
        angleChipHtml(root, combined, {
          combined: true,
          extraLabel:
            't' +
            Math.round(Number(combined.timing_pts || 0)) +
            ' · p' +
            Math.round(Number(combined.peer_pts || 0)),
          titleSuffix: 'timing ' + combined.timing_pts + ' · peer ' + combined.peer_pts,
        }) +
        '</div></section>';
    }
    html += '</div>';
    return html;
  }

  function renderPumpScanRow(row, tone) {
    var formPct =
      row.formation_pct != null
        ? Number(row.formation_pct)
        : row.score != null
          ? Math.min(100, Math.round(Number(row.score) * 100))
          : null;
    var badge = String(row.badge || '');
    var badgeSlug = badge.toLowerCase().replace(/\s+/g, '-');
    var shortBadge =
      {
        'WARMING UP': 'WARM',
        BUILDING: 'BUILD',
        STRONG: 'STRONG',
        'JUST STARTED': 'JUST',
        'CHASE RISK': 'CHASE',
        FADING: 'FADE',
        'NEAR GATE': 'NEAR',
      }[badge] || badge;
    var labels = row.triad_labels || {};
    var triad = row.triad || {};
    var why = row.trigger || row.subtitle || '';
    return (
      '<a class="pds-ladder pds-ladder--' +
      esc(tone) +
      '" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '"><div class="pds-ladder__head">' +
      '<span class="pds-ladder__badge pds-ladder__badge--' +
      esc(badgeSlug) +
      '">' +
      esc(shortBadge) +
      '</span>' +
      '<span class="pds-ladder__name">' +
      esc(pumpRowDisplayName(row)) +
      ' <b>SN' +
      esc(row.netuid) +
      '</b></span>' +
      '<span class="pds-ladder__nums"><span class="pds-ladder__num"><i>Flow</i>' +
      (formPct != null ? formPct : '—') +
      '</span><span class="pds-ladder__num pds-ladder__num--gap"><i>Gap</i>' +
      esc(row.distance != null ? row.distance : '—') +
      '</span></span></div>' +
      pumpPatternLineHtml(row) +
      (why ? '<p class="pds-ladder__why">' + esc(why) + '</p>' : '') +
      '<div class="pds-ladder__legs">' +
      '<span class="pds-ladder__leg' +
      (triad.inflow_quiet_load ? ' pds-ladder__leg--on' : '') +
      '">In ' +
      esc(labels.inflow || 'WATCH') +
      '</span>' +
      '<span class="pds-ladder__leg' +
      (triad.buy_pressure ? ' pds-ladder__leg--on' : '') +
      '">Pr ' +
      esc(labels.pressure || 'FLAT') +
      '</span>' +
      '<span class="pds-ladder__leg' +
      (triad.price_coil ? ' pds-ladder__leg--on' : '') +
      '">Coil ' +
      esc(labels.coil || 'OPEN') +
      '</span></div></a>'
    );
  }

  function renderPumpMetaWrap(trust, early, live, exitN) {
    if (isPumpScanMode()) {
      return renderPumpScanMetaWrap(trust, early, live, exitN);
    }
    var wrap = document.getElementById('pd-meta-wrap');
    if (!wrap) return;
    var census =
      '<div class="pd-census" id="pd-census" aria-label="Desk census">' +
      '<span class="pd-census__chip pd-census__chip--lead"><b id="pd-census-lead">' +
      early +
      '</b> lead</span>' +
      '<span class="pd-census__chip pd-census__chip--live"><b id="pd-census-live">' +
      live +
      '</b> live</span>' +
      '<span class="pd-census__chip pd-census__chip--exit"><b id="pd-census-exit">' +
      exitN +
      '</b> exit</span></div>';
    if (trust && trust.ready && trust.headline_pct != null) {
      var n = trust.headline_n != null ? trust.headline_n : (trust.early && trust.early.n) || 0;
      wrap.innerHTML =
        '<div class="pd-proof__ready" id="pump-alert-proof">' +
        '<span class="pd-proof__pct" id="pump-alert-proof-pct">' +
        esc(trust.headline_pct) +
        '%</span>' +
        '<span class="pd-proof__copy">early alerts hit +2% in 1h · n=' +
        esc(n) +
        '</span></div>' +
        census;
    } else {
      var line =
        (trust && trust.line) || 'Early alerts: grading starts once lead phase entries resolve (1h).';
      wrap.innerHTML =
        '<p class="pd-proof__building" id="pump-alert-trust">' + esc(line) + '</p>' + census;
    }
  }

  function renderPumpHeroCard(row) {
    if (!row || row.netuid == null) return '';
    var triad = row.triad || {};
    var labels = row.triad_labels || {};
    var score = row.score != null ? Number(row.score) : 0;
    var trigger = row.trigger_score != null ? Number(row.trigger_score) : 0.72;
    var trigPct = Math.min(100, Math.round((score / trigger) * 100));
    var formPct =
      row.formation_pct != null ? Number(row.formation_pct) : Math.min(100, Math.round(score * 100));
    var confirmPct =
      row.confirm_pct != null
        ? Number(row.confirm_pct)
        : row.momentum_pct != null
          ? Number(row.momentum_pct)
          : formPct;
    var timing = String(row.timing || 'lead');
    var badgeSlug = String(row.badge || '')
      .toLowerCase()
      .replace(/\s+/g, '-');
    var phase = String(row.phase || 'STIRRING').toUpperCase();
    var order = [
      ['STIRRING', 'Stir'],
      ['ACCUMULATING', 'Build'],
      ['PUMPING', 'Pump'],
      ['COOLING', 'Cool'],
    ];
    var phaseHtml =
      '<ol class="pd-phase" aria-label="Formation phase">' +
      order
        .map(function (pair) {
          return (
            '<li class="pd-phase__step' +
            (phase === pair[0] ? ' pd-phase__step--now' : '') +
            '">' +
            pair[1] +
            '</li>'
          );
        })
        .join('') +
      '</ol>';
    var progress = Array.isArray(row.progress_series) ? row.progress_series : [];
    var trendHtml =
      progress.length >= 2
        ? '<span class="pd-lead__trend"><span class="pump-progress" data-progress="' +
          esc(progress.join(',')) +
          '" role="img" aria-label="Score trend toward trigger"></span></span>'
        : '';
    var move = row.move || (row.badge || '') + ' · ' + (row.name || '');
    var thesis = row.thesis || '';
    var triggerCopy = row.trigger || row.subtitle || '';
    var chipsHtml = '';
    if (row.size_line) chipsHtml += '<p class="pd-chip">' + esc(row.size_line) + '</p>';
    if (row.whale_archetype)
      chipsHtml += '<p class="pd-chip pd-chip--whale">' + esc(row.whale_archetype) + '</p>';
    if (row.wallet_chip) chipsHtml += '<p class="pd-chip pd-chip--wallet">' + esc(row.wallet_chip) + '</p>';
    chipsHtml += renderRugHistoryChip(row, 'pd-chip');
    if (row.telegram_chip)
      chipsHtml += '<p class="pd-chip pd-chip--tg">' + esc(row.telegram_chip) + '</p>';
    if (row.owner_chip) chipsHtml += '<p class="pd-chip pd-chip--owner">' + esc(row.owner_chip) + '</p>';
    var patternLine = pumpPatternLineHtml(row, 'pump-pattern-line--hero');
    var highlightCls = row.pattern_highlight ? ' pd-lead--pattern-highlight' : '';
    return (
      '<article class="pd-lead pd-lead--' +
      esc(timing) +
      highlightCls +
      ' pump-hero__card" id="pump-desk-hero" data-netuid="' +
      esc(row.netuid) +
      '" data-name="' +
      esc(pumpRowDisplayName(row)) +
      '">' +
      '<div class="pd-lead__identity">' +
      '<span class="pd-lead__badge pd-lead__badge--' +
      esc(badgeSlug) +
      '">' +
      esc(row.badge || '') +
      '</span>' +
      '<div class="pd-lead__who"><a class="pd-lead__name" href="/subnet/' +
      esc(row.netuid) +
      '">' +
      esc(pumpRowDisplayName(row)) +
      ' <b class="pd-lead__sn">SN' +
      esc(row.netuid) +
      '</b></a>' +
      (row.updated_ago ? '<span class="pd-lead__ago">' + esc(row.updated_ago) + '</span>' : '') +
      '</div>' +
      '<div class="pd-lead__meter" aria-label="' +
      trigPct +
      ' percent of the way to trigger"><span class="pd-lead__meter-val">' +
      trigPct +
      '<i>%</i></span><span class="pd-lead__meter-lbl">to trigger</span></div></div>' +
      patternLine +
      '<div class="pd-lead__bar" role="progressbar" aria-valuenow="' +
      trigPct +
      '" aria-valuemin="0" aria-valuemax="100"><span class="pd-lead__bar-fill" style="width:' +
      trigPct +
      '%"></span>' +
      trendHtml +
      '</div>' +
      phaseHtml +
      '<div class="pd-verdict"><p class="pd-verdict__move">' +
      esc(move) +
      '</p>' +
      (thesis ? '<p class="pd-verdict__thesis">' + esc(thesis) + '</p>' : '') +
      (triggerCopy ? '<p class="pd-verdict__trigger">' + esc(triggerCopy) + '</p>' : '') +
      '</div>' +
      '<div class="pd-evidence" aria-label="Formation metrics">' +
      renderPumpMetricsBar(row, 'pd') +
      '</div>' +
      _pdTriadLegs(triad, labels) +
      chipsHtml +
      renderAnglesBlock(row, 'pd-angles') +
      '<div class="pd-cta" role="group" aria-label="Lead actions">' +
      '<a class="home-cta home-cta--primary" id="pump-desk-cta" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '" data-name="' +
      esc(pumpRowDisplayName(row)) +
      '">' +
      esc(pumpDossierCtaLabel(row)) +
      '</a>' +
      '<a class="home-cta home-cta--ghost" href="#pro-cockpit">Open depth</a></div></article>'
    );
  }

  function pumpRowDisplayName(row) {
    if (!row) return '';
    return resolveSubnetDisplayName({ name: row.name, netuid: row.netuid }, row.netuid);
  }

  function pumpDossierCtaLabel(rowOrName, netuid) {
    var name =
      rowOrName && typeof rowOrName === 'object'
        ? pumpRowDisplayName(rowOrName)
        : String(rowOrName || '').trim();
    var nu =
      netuid != null
        ? netuid
        : rowOrName && typeof rowOrName === 'object'
          ? rowOrName.netuid
          : null;
    if (nu == null || nu === '') return 'Open dossier';
    if (!name) name = 'SN' + nu;
    return 'Open ' + name + ' SN' + nu + ' dossier';
  }

  function patchPumpDeskCta(row) {
    var cta = document.getElementById('pump-desk-cta');
    if (!cta) return;
    var hero = document.getElementById('pump-desk-hero');
    var source = row || hero;
    if (!source) {
      var ladder = document.querySelector('.pds-ladder[data-netuid], .pd-r[data-netuid]');
      if (ladder) {
        source = {
          netuid: ladder.getAttribute('data-netuid'),
          name: ladder.getAttribute('data-name'),
        };
      }
    }
    if (!source || source.netuid == null) {
      cta.textContent = 'Open dossier';
      return;
    }
    var nu = source.netuid;
    var name = source.name || (hero && hero.getAttribute('data-name')) || null;
    cta.href = '/subnet/' + encodeURIComponent(String(nu));
    cta.setAttribute('data-netuid', String(nu));
    if (name) cta.setAttribute('data-name', String(name));
    cta.textContent = pumpDossierCtaLabel(name ? { name: name, netuid: nu } : { netuid: nu }, nu);
  }

  function renderPumpDeskRow(row, tone) {
    var formPct =
      row.formation_pct != null
        ? Number(row.formation_pct)
        : row.score != null
          ? Math.min(100, Math.round(Number(row.score) * 100))
          : null;
    var badge = String(row.badge || '');
    var badgeSlug = badge.toLowerCase().replace(/\s+/g, '-');
    var shortBadge =
      {
        'WARMING UP': 'WARM',
        BUILDING: 'BUILD',
        STRONG: 'STRONG',
        'JUST STARTED': 'JUST',
        'CHASE RISK': 'CHASE',
        FADING: 'FADE',
        'NEAR GATE': 'NEAR',
      }[badge] || badge;
    var why = row.trigger || row.subtitle || row.badge || '';
    if (why.length > 72) why = why.slice(0, 69).replace(/\s+\S*$/, '') + '…';
    return (
      '<a class="pd-r pd-r--' +
      esc(tone) +
      ' pump-desk__row" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '" title="' +
      esc(badge) +
      '">' +
      '<div class="pd-r__top"><div class="pd-r__id">' +
      '<span class="pd-r__badge pd-r__badge--' +
      esc(badgeSlug) +
      '">' +
      esc(shortBadge) +
      '</span>' +
      '<span class="pd-r__name">' +
      esc(pumpRowDisplayName(row)) +
      ' <b class="pd-r__sn">SN' +
      esc(row.netuid) +
      '</b></span></div>' +
      '<div class="pd-r__nums" aria-label="Flow and gap">' +
      '<span class="pd-r__num"><i>Flow</i> ' +
      (formPct != null ? formPct : '—') +
      '</span>' +
      '<span class="pd-r__num pd-r__num--gap"><i>Gap</i> ' +
      esc(row.distance != null ? row.distance : '—') +
      '</span></div></div>' +
      pumpPatternLineHtml(row) +
      (why ? '<p class="pd-r__why">' + esc(why) + '</p>' : '') +
      _pdTriadLegs(row.triad, row.triad_labels, 'pd-r__leg') +
      '</a>'
    );
  }

  function pumpDeskLiveHost() {
    var deskPanel = document.getElementById('pump-desk-panel');
    if (!deskPanel) return null;
    return deskPanel.querySelector('.pds-desk__live') || deskPanel;
  }

  function renderPumpDeskPanel(alerts, emptyMessage, payload) {
    var liveHost = pumpDeskLiveHost();
    if (!liveHost) return;
    var compact = !!document.querySelector('[data-pump-compact="1"]');
    var warm = (alerts || []).filter(function (r) {
      return r.timing === 'lead';
    });
    var active = (alerts || []).filter(function (r) {
      return r.timing === 'confirmed';
    });
    var exits = (alerts || []).filter(function (r) {
      return r.timing === 'exit';
    });
    if (!warm.length && !active.length) {
      var watch = (payload && payload.watch) || [];
      if (watch.length) {
        var watchHtml =
          '<p class="pds-empty-note">No lead alerts yet — these names are STIRRING below the gate.</p>' +
          '<h3 class="pds-board__lbl pds-board__lbl--watch">Almost warming <span>' +
          watch.length +
          '</span></h3>';
        watch.forEach(function (row) {
          watchHtml += renderPumpScanRow(row, 'watch');
        });
        liveHost.innerHTML = watchHtml;
        if (typeof window.__paintSparks === 'function') window.__paintSparks();
        return;
      }
      liveHost.innerHTML =
        '<p class="' +
        (isPumpScanMode() ? 'pds-empty' : 'pd-empty') +
        ' pump-desk__empty">' +
        esc(emptyMessage || 'Quiet — no warming or active names on the ladder right now.') +
        '</p>';
      return;
    }
    var hero = (payload && payload.hero) || warm[0] || active[0];
    var html = '';
    if (compact && hero) {
      if (isPumpScanMode()) {
        html += renderPumpScanHeroCard(hero);
        var moreScan = '';
        if (warm.length > 1) {
          moreScan +=
            '<h3 class="pds-board__lbl">Also warming <span>' +
            (warm.length - 1) +
            '</span></h3>';
          warm.slice(1).forEach(function (row) {
            moreScan += renderPumpScanRow(row, 'warm');
          });
        }
        if (active.length) {
          moreScan +=
            '<h3 class="pds-board__lbl pds-board__lbl--chase">Active · chase risk <span>' +
            active.length +
            '</span></h3>';
          active.forEach(function (row) {
            moreScan += renderPumpScanRow(row, 'active');
          });
        }
        if (exits.length) {
          moreScan +=
            '<h3 class="pds-board__lbl pds-board__lbl--exit">Cooling <span>' +
            exits.length +
            '</span></h3>';
          exits.forEach(function (row) {
            moreScan += renderPumpScanRow(row, 'exit');
          });
        }
        if (moreScan) html += '<div class="pds-board" id="pump-desk-more">' + moreScan + '</div>';
        renderPumpMetaWrap(payload && payload.trust, warm.length, active.length, exits.length);
        liveHost.innerHTML = html;
        if (typeof window.__paintSparks === 'function') window.__paintSparks();
        return;
      }
      html += renderPumpHeroCard(hero);
      var more = '';
      if (warm.length > 1) {
        more +=
          '<section class="pd-board__section"><h4 class="pd-board__lbl">Also warming <span>' +
          (warm.length - 1) +
          '</span></h4><div class="pd-board__rows">';
        warm.slice(1).forEach(function (row) {
          more += renderPumpDeskRow(row, 'warm');
        });
        more += '</div></section>';
      }
      if (active.length) {
        more +=
          '<section class="pd-board__section"><h4 class="pd-board__lbl">Active · chase risk <span>' +
          active.length +
          '</span></h4><div class="pd-board__rows">';
        active.forEach(function (row) {
          more += renderPumpDeskRow(row, 'active');
        });
        more += '</div></section>';
      }
      if (exits.length) {
        more +=
          '<section class="pd-board__section"><h4 class="pd-board__lbl">Cooling · exit watch <span>' +
          exits.length +
          '</span></h4><div class="pd-board__rows">';
        exits.forEach(function (row) {
          more += renderPumpDeskRow(row, 'exit');
        });
        more += '</div></section>';
      }
      if (more) html += '<div class="pd-board" id="pump-desk-more">' + more + '</div>';
      renderPumpMetaWrap(payload && payload.trust, warm.length, active.length, exits.length);
      liveHost.innerHTML = html;
      if (typeof window.__paintSparks === 'function') window.__paintSparks();
      return;
    }
    if (warm.length) {
      html += '<h4 class="pd-board__lbl">Warming</h4><div class="pd-board__rows">';
      warm.forEach(function (row) {
        html += renderPumpDeskRow(row, 'warm');
      });
      html += '</div>';
    }
    if (active.length) {
      html += '<h4 class="pd-board__lbl">Active</h4><div class="pd-board__rows">';
      active.forEach(function (row) {
        html += renderPumpDeskRow(row, 'active');
      });
      html += '</div>';
    }
    if (exits.length) {
      html += '<h4 class="pd-board__lbl">Cooling</h4><div class="pd-board__rows">';
      exits.forEach(function (row) {
        html += renderPumpDeskRow(row, 'exit');
      });
      html += '</div>';
    }
    liveHost.innerHTML = html;
    if (typeof window.__paintSparks === 'function') window.__paintSparks();
  }

  function pumpDeskHasSnapshot() {
    return !!(
      document.querySelector('.pump-desk__row') ||
      document.querySelector('.pump-hero__card') ||
      document.querySelector('.pd-lead') ||
      document.querySelector('.pds-hero') ||
      document.querySelector('.pd-row') ||
      document.querySelector('.pds-ladder')
    );
  }

  function renderPumpAlerts(payload) {
    var body = document.getElementById('pump-alert-body');
    if (!body || !payload) return;
    var payloadStatus = String(payload.status || '').toLowerCase();
    if (
      payloadStatus === 'timeout' ||
      payloadStatus === 'error' ||
      payloadStatus === 'unavailable' ||
      payload.error === 'worker_volume_proxy_failed'
    ) {
      if (pumpDeskHasSnapshot()) return;
    }
    var listPanel = document.getElementById('pump-list-panel');
    var trust = payload.trust || {};
    var alerts = payload.alerts || [];
    var earlyCount = Number(payload.early_count);
    var confirmedCount = Number(payload.confirmed_count);
    var exitCount = Number(payload.exit_count);
    if (!earlyCount && !confirmedCount) {
      earlyCount = alerts.filter(function (r) { return r.timing === 'lead'; }).length;
      confirmedCount = alerts.filter(function (r) { return r.timing === 'confirmed'; }).length;
    }
    if (!exitCount) {
      exitCount = alerts.filter(function (r) { return r.timing === 'exit'; }).length;
    }
    var count = Number(payload.count) || earlyCount + confirmedCount;
    var compact = !!document.querySelector('[data-pump-compact="1"]');
    var countEl = document.getElementById('pump-alert-count');
    if (compact) {
      renderPumpMetaWrap(trust, earlyCount, confirmedCount, exitCount);
    } else if (countEl) {
      countEl.textContent = count > 0 ? earlyCount + ' warming · ' + confirmedCount + ' active' : '';
      countEl.style.display = count > 0 ? '' : 'none';
    }
    if (!count && !exitCount) {
      var watchRows = payload.watch || [];
      if (!watchRows.length) {
        if (pumpDeskHasSnapshot()) return;
      var liveHost = pumpDeskLiveHost();
      if (liveHost) {
        liveHost.innerHTML =
          '<p class="pd-empty pump-desk__empty">' +
          esc(
            payload.empty_message ||
              "Quiet — no warming or active names on the ladder right now."
          ) +
          '</p>';
      }
      if (listPanel) {
        listPanel.hidden = true;
        listPanel.innerHTML = '';
      }
      var emptyMap = document.getElementById('pump-map-data');
      if (emptyMap) emptyMap.textContent = '[]';
      if (window.PumpMap) window.PumpMap.refresh([]);
      return;
      }
      renderPumpDeskPanel([], payload.empty_message, payload);
      if (listPanel) {
        listPanel.hidden = true;
        listPanel.innerHTML = '';
      }
      var watchMap = document.getElementById('pump-map-data');
      if (watchMap) watchMap.textContent = '[]';
      if (window.PumpMap) window.PumpMap.refresh([]);
      return;
    }
    var mapRows = [];
    var html = '';
    renderPumpDeskPanel(alerts, payload.empty_message, payload);
    alerts.forEach(function (row) {
      if (row.timing !== 'lead' && row.timing !== 'confirmed' && row.timing !== 'exit') return;
      mapRows.push(row);
      var timing = String(row.timing || 'confirmed');
      var phase = String(row.phase || '').toLowerCase();
      var badge = String(row.badge || '').toLowerCase().replace(/\s+/g, '-');
      var name = esc(pumpRowDisplayName(row));
      var sn = row.netuid != null ? ' <span class="pump-alert__sn">SN' + esc(row.netuid) + '</span>' : '';
      html +=
        '<article class="pump-alert__card pump-alert__card--' +
        esc(timing) +
        ' pump-alert__card--' +
        esc(phase) +
        '" role="listitem" data-netuid="' +
        esc(row.netuid) +
        '" data-timing="' +
        esc(timing) +
        '">' +
        '<div class="pump-alert__card-top">' +
        '<a class="pump-alert__name" href="/subnet/' +
        esc(row.netuid) +
        '">' +
        name +
        sn +
        '</a>' +
        '<span class="pump-alert__badge pump-alert__badge--' +
        esc(badge) +
        '">' +
        esc(row.badge || '') +
        '</span></div>';
      if (row.score != null) {
        var pct = Math.min(100, Math.round(Number(row.score) * 100));
        html +=
          '<div class="pump-alert__meter" aria-hidden="true"><span class="pump-alert__meter-fill" style="width:' +
          pct +
          '%"></span></div>';
      }
      var triad = row.triad || {};
      if (triad.inflow_quiet_load != null || triad.buy_pressure != null || triad.price_coil != null) {
        html += '<div class="pump-alert__triad" aria-label="Pre-pump triad">';
        ['inflow_quiet_load', 'buy_pressure', 'price_coil'].forEach(function (key, idx) {
          var labels = ['Inflow', 'Pressure', 'Coil'];
          var on = triad[key] ? ' pump-alert__triad-leg--on' : '';
          html +=
            '<span class="pump-alert__triad-leg' +
            on +
            '">' +
            esc(labels[idx]) +
            '</span>';
        });
        html += '</div>';
      }
      html +=
        '<p class="pump-alert__thesis">' +
        esc(row.thesis || '') +
        '</p>';
      if (row.size_line) {
        html += '<p class="pump-alert__size">' + esc(row.size_line) + '</p>';
      }
      if (row.wallet_chip) {
        html += '<p class="pump-alert__wallet-chip">' + esc(row.wallet_chip) + '</p>';
      }
      var dayChips = Array.isArray(row.whale_day_chips) ? row.whale_day_chips : [];
      dayChips.forEach(function (chip) {
        if (!chip) return;
        html +=
          '<p class="pump-alert__wallet-chip pump-alert__wallet-chip--day">' +
          esc(chip) +
          '</p>';
      });
      html +=
        '<p class="pump-alert__trigger">' +
        esc(row.trigger || '') +
        '</p></article>';
    });
    if (listPanel) {
      if (compact) {
        listPanel.hidden = true;
        listPanel.innerHTML = '';
      } else {
        listPanel.innerHTML =
          '<div class="pump-alert__lane" id="pump-alert-list" role="list">' + html + '</div>';
        listPanel.hidden = false;
      }
    }
    var mapData = document.getElementById('pump-map-data');
    if (mapData) mapData.textContent = JSON.stringify(mapRows);
    if (window.PumpMap) window.PumpMap.refresh(mapRows);
    if (typeof window.__paintSparks === 'function') window.__paintSparks();
    renderProofPumpTab(trust);
    var heroForCta = payload.hero;
    if (!heroForCta && alerts.length) {
      heroForCta =
        alerts.find(function (r) {
          return r.timing === 'lead';
        }) || alerts[0];
    }
    patchPumpDeskCta(heroForCta);
  }

  function renderDailyPick(payload) {
    // §34-1 / K3-7: patch K3 dossier fields — never wipe #k3-dossier via innerHTML
    if (!payload) return;
    var shouldApply = shouldApplyDailyPickPayload(payload);
    // #region agent log
    debugHydration('C', 'daily pick patch decision', {
      status: payload.status || null,
      action: payload.action || null,
      hasPick: !!payload.pick,
      hasCandidate: !!payload.candidate,
      shouldApply: shouldApply,
      hero: !!document.getElementById('tribunal-hero'),
    });
    // #endregion
    if (!shouldApply) {
      console.warn('[cockpit_hydrate] daily-pick patch skipped (stale/pending)');
      return;
    }
    lastDailyPickPayload = payload;
    if (document.getElementById('tribunal-hero')) {
      patchK3DossierFromPayload(payload);
      renderTribunalHero(payload, window.SimiLearning && window.SimiLearning.stats);
      loadLearningStats().then(function (stats) {
        renderTribunalHero(
          payload,
          stats || (window.SimiLearning && window.SimiLearning.stats)
        );
      });
      return;
    }
    if (patchK3DossierFromPayload(payload)) return;

    var host = document.getElementById('home-daily-call');
    if (!host) host = document.getElementById('council-stage-body');
    if (!host) return;

    var act = String(payload.action || 'HOLD').toUpperCase();
    if (act === 'LONG') act = 'BUY';
    var pick = payload.pick;
    var cand = payload.candidate;
    var active = pick || cand;
    var sn = (active && active.subnet) || {};
    var confSrc = active || payload;
    // H1: intentionally out of scope — secondary council-call card, not hero orb
    var finalConf = confSrc.final_confidence != null ? confSrc.final_confidence : confSrc.confidence;
    var fc = confTier(finalConf != null ? finalConf : 0);
    var audit = (active && active.audit) || {};
    var concerns = (audit.concerns || []).slice(0, 4);
    var why =
      (pick && pick.reasons && pick.reasons[0]) ||
      (cand && cand.reasons && cand.reasons[0]) ||
      payload.reason ||
      '';

    var html;
    if (pick && (sn.name != null || sn.netuid != null)) {
      var reasons = (pick.reasons || []).slice(0, 3);
      html =
        '<div class="council-call home-job__call">' +
        '<div class="council-call__action">' +
        '<span class="badge ' + recBadge(act) + '">' + esc(act) + '</span>' +
        (audit.approved ? '<span class="hero-audit">AUDIT PASSED</span>' : '') +
        '</div>' +
        '<p class="council-call__name">' + esc(resolveSubnetDisplayName(sn, sn.netuid)) + '</p>' +
        '<p class="council-call__meta">SN' + esc(sn.netuid != null ? sn.netuid : pickNetuid(pick)) +
        (sn.symbol ? ' · ' + esc(sn.symbol) : '') +
        (finalConf != null ? ' · ' + fc.conf + '% confidence' : '') +
        '</p>' +
        (why ? '<p class="home-job__why">We expect: ' + esc(why) + '</p>' : '') +
        (reasons.length > 1
          ? '<ul class="council-call__reasons">' +
            reasons.slice(1).map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') +
            '</ul>'
          : '') +
        (concerns.length
          ? '<ul class="council-call__concerns">' +
            concerns.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') +
            '</ul>'
          : '') +
        '</div>';
    } else {
      html =
        '<div class="council-call council-call--hold home-job__call">' +
        '<div class="council-call__action"><span class="badge badge-hold">HOLD</span></div>';
      if (sn.name != null || sn.netuid != null) {
        html +=
          '<p class="council-call__name">' + esc(resolveSubnetDisplayName(sn, sn.netuid)) + '</p>' +
          '<p class="council-call__meta">SN' + esc(sn.netuid) +
          (sn.symbol ? ' · ' + esc(sn.symbol) : '') +
          ' · candidate only' +
          (finalConf != null ? ' · ' + fc.conf + '%' : '') +
          '</p>';
      } else {
        html += '<p class="council-call__name">No audited long call</p>';
      }
      html +=
        '<p class="home-job__why">' +
        esc(why || ('Council waits until confidence clears the ' + (window.PUBLISH_GATE_LABEL || '40% audit gate') + '.')) +
        '</p>';
      if (concerns.length) {
        html +=
          '<ul class="council-call__concerns">' +
          concerns.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') +
          '</ul>';
      }
      html += '</div>';
    }

    host.innerHTML = html;

    var pin = document.getElementById('habit-pin-btn');
    if (pin && sn.netuid != null) {
      pin.dataset.netuid = String(sn.netuid);
      pin.disabled = false;
      pin.removeAttribute('aria-disabled');
    }
    try {
      document.dispatchEvent(new CustomEvent('home-daily-call-updated'));
    } catch (e) {}
    renderStageWhyNot(sn.netuid, act);
  }

  function renderStageWhyNot(netuid, action) {
    var panel = document.getElementById('home-stage-why-not');
    if (!panel) return;
    if (netuid == null || String(action || '').toUpperCase() === 'LONG' || String(action || '').toUpperCase() === 'BUY') {
      panel.hidden = true;
      panel.innerHTML = '';
      return;
    }
    fetchJsonTimeout('/api/pick-explain/' + encodeURIComponent(netuid), 10000)
      .then(function (explain) {
        if (!explain || !explain.blockers || !explain.blockers.length) {
          panel.hidden = true;
          panel.innerHTML = '';
          return;
        }
        var blockers = dedupeBlockers(explain.blockers).slice(0, 4);
        panel.hidden = false;
        panel.innerHTML =
          '<p class="home-stage-why-not__title">Why no audited long</p>' +
          '<ul class="home-stage-why-not__list">' +
          blockers.map(function (b) { return '<li>' + esc(b) + '</li>'; }).join('') +
          '</ul>';
      })
      .catch(function () {
        panel.hidden = true;
      });
  }

  function renderPickCards(picks, horizon) {
    horizon = horizon === 'day' ? 'day' : 'hour';
    return (picks || []).map(function (pick, idx) {
      var tags = pick.scenario_tags || {};
      var isFallback = !!tags.fallback;
      var isHold = String(pick.action || '').toUpperCase() === 'HOLD';
      var t = confTier(pick.confidence || 0);
      var statusLine = '';
      if (isFallback) {
        statusLine = '<div class="pick-degraded-note">⚠ Council scoring unavailable — not a scored call</div>';
      } else if (isHold) {
        statusLine = '<div class="pick-degraded-note pick-degraded-note--hold">HOLD' + (pick.hold_reason ? ' · ' + esc(pick.hold_reason) : '') + '</div>';
      }
      var leadClass =
        idx === 0 ? ' pick-card--lead pick-card--lead-' + horizon : '';
      return (
        '<div class="pick-card pick-card--reveal' +
        leadClass +
        (isFallback ? ' pick-card--degraded' : '') +
        '" style="--pick-i:' +
        idx +
        '">' +
        '<div class="pick-rank">#' + (idx + 1) + '</div>' +
        '<div class="pick-name">' + esc(pickName(pick)) + '</div>' +
        '<div class="pick-meta">SN' + esc(pickNetuid(pick)) + ' · score <b class="accent-bright">' + fmt(pick.score, 1) + '</b></div>' +
        '<div class="conviction-bar"><div class="conviction-fill ' + t.tier + '" style="width:' + t.conf + '%;"></div></div>' +
        statusLine +
        '</div>'
      );
    }).join('');
  }

  function renderHourDayPicks(hourPicks, dayPicks) {
    lastHourPicks = hourPicks || [];
    lastDayPicks = dayPicks || [];
    if (!(hourPicks && hourPicks.length) && !(dayPicks && dayPicks.length)) return;
    var html =
      '<div class="two-col">' +
      '<div class="card"><div class="card-head"><h3>Hour Horizon</h3><span class="src-tag">top ' + (hourPicks || []).length + ' · 1h</span></div>' +
      '<div class="picks">' + (hourPicks && hourPicks.length ? renderPickCards(hourPicks, 'hour') : '<p class="empty">No hour picks yet.</p>') + '</div></div>' +
      '<div class="card"><div class="card-head"><h3>Day Horizon</h3><span class="src-tag">top ' + (dayPicks || []).length + ' · 24h</span></div>' +
      '<div class="picks">' + (dayPicks && dayPicks.length ? renderPickCards(dayPicks, 'day') : '<p class="empty">No day picks yet.</p>') + '</div></div></div>';
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
    if (!trail || !trail.length) {
      replaceEmptyIn(
        'section-trail',
        '<div class="card card-muted"><p class="empty empty--quiet">No trace events yet — the trail will fill as Council decisions are recorded.</p></div>'
      );
      return;
    }
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

  var SOUL_ORB_COLORS = { quant: '#3fc9ff', hype: '#ff5fa8', dark_horse: '#a78bfa', technical: '#ffb74a' };
  var SOUL_ORB_FALLBACK = ['#3fc9ff', '#a78bfa', '#ffb74a', '#ff5fa8', '#34d399', '#60a5fa'];
  // Match SSR `_council_weights_list`: trend vs neutral default 1.0, not ephemeral deltas.
  var SOUL_WEIGHT_BASELINE = 1.0;

  function soulTrendFromWeight(w) {
    var n = Number(w);
    if (isNaN(n)) return 'even';
    if (n > SOUL_WEIGHT_BASELINE + 0.005) return 'up';
    if (n < SOUL_WEIGHT_BASELINE - 0.005) return 'down';
    return 'even';
  }

  function councilBiasLabel(trend, expertGraded, weight) {
    var sample = 'n=' + String(expertGraded || 0);
    if ((expertGraded || 0) <= 0) return 'PRIOR · ' + sample;
    if (Number(weight) >= 2.0) return '\u25B2 CAPPED · ' + sample;
    if (trend === 'up') return '\u25B2 LEARNED UP · ' + sample;
    if (trend === 'down') return '\u25BC LEARNED DOWN · ' + sample;
    return 'EVEN · ' + sample;
  }

  function soulTrendFromDelta(delta, w, expertGraded) {
    if ((expertGraded || 0) <= 0) return 'prior';
    var d = Number(delta);
    if (!isNaN(d) && Math.abs(d) > 0.001) {
      if (d > 0) return 'up';
      if (d < 0) return 'down';
      return 'even';
    }
    return soulTrendFromWeight(w);
  }

  function renderCouncilWeights(weights, deltas, expertGraded) {
    var normalized = normalizeWeights(weights);
    var keys = CANONICAL_EXPERTS.filter(function (k) { return normalized[k] != null; });
    if (!keys.length) return;
    var deltaMap = deltas && typeof deltas === 'object' ? deltas : {};
    var gradedMap = expertGraded && typeof expertGraded === 'object' ? expertGraded : {};
    var ranked = keys.slice().sort(function (a, b) { return (normalized[b] || 0) - (normalized[a] || 0); });
    var top = ranked[0];
    var cards = ranked.map(function (name, index) {
      var w = Number(normalized[name]) || 0;
      var gradedN = Number(gradedMap[name]) || 0;
      var trend = soulTrendFromDelta(deltaMap[name], w, gradedN);
      var biasLabel = councilBiasLabel(trend, gradedN, w);
      var orbColor = SOUL_ORB_COLORS[name] || SOUL_ORB_FALLBACK[index % SOUL_ORB_FALLBACK.length];
      var orbPx = Math.round(58 + Math.min(w, 2.0) / 2.0 * 46);
      return (
        '<div class="expert card-soft card soul-orb-card" style="--soulmap-delay:' + (index * 0.35).toFixed(2) + 's;">' +
        '<div class="soul-orb-wrap"><div class="soul-orb soul-orb--' + trend + '" style="--orb-accent:' + orbColor + ';--orb-px:' + orbPx + 'px;">' +
        '<span class="soul-orb-core"></span><span class="soul-orb-value">' + fmt(w, 2) + '</span>' +
        '</div></div>' +
        '<div class="name">' + esc(expertLabel(name)) + '</div>' +
        '<span class="bias trend-' + trend + '">' + biasLabel + '</span></div>'
      );
    }).join('');
    var lean = top
      ? '<p class="council-lean">Leaning <strong>' + esc(expertLabel(top)) + '</strong> · weight ' + fmt(normalized[top], 3) + '</p>'
      : '';
    replaceSectionContent('section-council', lean + '<div class="council-grid soulmap-constellation">' + cards + '</div>', '.council-grid, .card-muted');
    patchK3CouncilVotes(weights, deltaMap);
    renderWeightNudgeLine(deltaMap);
  }


  function renderKpi(stats) {
    if (!stats) return;
    var section = document.getElementById('section-kpi');
    if (!section) return;
    var strip = section.querySelector('.kpi-strip');
    if (!strip) return;

    var tb = stats.trust_banner;
    var hasTrust = tb && typeof tb === 'object';
    var accRaw = hasTrust && tb.accuracy != null ? tb.accuracy : null;
    var acc = accRaw != null ? Math.round(Number(accRaw) * 1000) / 10 : null;
    var graded = hasTrust && tb.graded != null ? Number(tb.graded) : 0;
    var correct = hasTrust ? Number(tb.correct || 0) : 0;
    var wrong = hasTrust ? Number(tb.wrong || 0) : 0;
    var expired = hasTrust && tb.expired != null ? Number(tb.expired) : null;
    var expiredRate = hasTrust && tb.expired_rate != null ? tb.expired_rate : null;
    var priceUnavailable = hasTrust && tb.price_data_unavailable != null
      ? Number(tb.price_data_unavailable)
      : 0;
    var expiredPct = expiredRate != null ? Math.round(Number(expiredRate) * 1000) / 10 : null;
    var wd = hasTrust ? (tb.watchdog || stats.watchdog || {}) : (stats.watchdog || {});
    var ready = hasTrust && tb.ready != null ? tb.ready : stats.brain_ui_ready;

    var accEl = document.getElementById('kpi-accuracy');
    if (accEl) {
      /* RF-2: never paint accuracy until integrity gate ready */
      accEl.textContent = ready && acc != null && graded > 0 ? acc + '%' : '—';
      accEl.className = 'val' + (ready && acc != null && acc >= 50 ? ' pos' : ready && acc != null && acc > 0 ? ' neg' : '');
    }
    var accCard = document.getElementById('kpi-accuracy-card');
    if (accCard) {
      if (ready && acc != null && graded > 0) {
        accCard.style.setProperty('--kpi-p', String(acc));
        accCard.classList.toggle('kpi--accuracy-gauge--lime', acc >= 50);
        accCard.classList.toggle('kpi--accuracy-gauge--amber', acc < 50 && acc > 0);
      } else {
        accCard.style.removeProperty('--kpi-p');
        accCard.classList.remove('kpi--accuracy-gauge--lime', 'kpi--accuracy-gauge--amber');
      }
    }
    var gradedEl = document.getElementById('kpi-graded');
    if (gradedEl) {
      if (hasTrust && ready && graded > 0) {
        gradedEl.textContent = correct + '✓ / ' + wrong + '✗ graded (n=' + graded + ')';
      } else if (hasTrust && tb.message) {
        gradedEl.textContent = tb.message;
      } else if (hasTrust && graded > 0) {
        gradedEl.textContent = graded + ' graded · trust gate pending';
      } else {
        gradedEl.textContent = '— graded (trust banner building)';
      }
    }
    if (hasTrust) syncProofBandFromTrust(tb);
    else syncProofBandGraded(0);
    syncProofEvidencePanels(tb, {
      working_count: stats.working && stats.working.top_price_signals
        ? stats.working.top_price_signals.length
        : null,
      council_pending: stats.council_pending,
      pump_pending: stats.pump_pending,
      alignment_diagnostic_events: stats.alignment_diagnostic_events,
    });
    var expEl = document.getElementById('kpi-expired');
    if (expEl) {
      expEl.textContent = expired != null ? String(expired) : '—';
      expEl.className = 'val' + (expiredPct != null && expiredPct >= 10 ? ' neg' : '');
    }
    var expRateEl = document.getElementById('kpi-expired-rate');
    if (expRateEl) {
      expRateEl.textContent = expiredPct != null
        ? expiredPct + '% of resolved flow' + (priceUnavailable ? ' · ' + priceUnavailable + ' missing price' : '')
        : 'resolver backlog';
    }
    var pendEl = document.getElementById('kpi-pending');
    if (pendEl) {
      pendEl.textContent = hasTrust && tb.pending != null ? String(tb.pending) : String(stats.pending || 0);
    }
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
      } else if (hasTrust && tb.message) {
        wdEl.textContent = tb.message;
      } else if (ready) {
        wdEl.textContent = 'trust surfaces unlocked';
      } else {
        wdEl.textContent = 'expired < 10% + n≥30 required';
      }
    }
    var trustWhisper = document.getElementById('council-trust-whisper');
    if (trustWhisper && hasTrust && graded > 0 && acc != null) {
      var line = graded + ' graded · ' + acc + '% dir.';
      if (tb.streak_whisper) line += ' · ' + tb.streak_whisper;
      trustWhisper.textContent = line;
    }
  }

  function pctLabel(rate) {
    if (rate == null || isNaN(rate)) return '—';
    return (Number(rate) * 100).toFixed(1) + '%';
  }

  function renderCalibrationChart(judgeName, bins) {
    if (!bins || !bins.length) return '';
    var active = bins.filter(function (b) { return (b.count || 0) > 0; });
    if (!active.length) {
      return '<p class="backtest-cal__empty">No score bins with samples yet.</p>';
    }
    var bars = active.map(function (b) {
      var hr = b.hit_rate != null ? Number(b.hit_rate) : 0;
      var pct = Math.round(hr * 1000) / 10;
      var h = Math.max(4, Math.min(100, pct));
      var mid = b.score_mid != null ? b.score_mid : ((Number(b.score_lo) + Number(b.score_hi)) / 2);
      return '<div class="backtest-cal__bar" title="score ' + mid + ' · n=' + b.count + ' · hit ' + pct + '%">' +
        '<div class="backtest-cal__bar-fill" style="height:' + h + '%;"></div>' +
        '<div class="backtest-cal__bar-label">' + mid + '</div></div>';
    }).join('');
    return '<div class="backtest-cal__chart" role="img" aria-label="' + esc(judgeName) + ' calibration reliability diagram">' +
      bars + '</div>';
  }

  function renderRiskCoverageTable(points) {
    if (!points || !points.length) return '';
    var rows = points.filter(function (p) { return (p.n || 0) > 0; }).slice(0, 6);
    if (!rows.length) return '';
    var body = rows.map(function (p) {
      return '<tr><td class="mono">≥' + p.threshold + '</td><td class="mono">' + pctLabel(p.hit_rate) + '</td>' +
        '<td class="mono">' + (p.coverage_pct != null ? p.coverage_pct + '%' : '—') + '</td><td class="mono">' + p.n + '</td></tr>';
    }).join('');
    return '<table class="tbl tbl--compact backtest-rc"><thead><tr><th>τ</th><th>Hit</th><th>Coverage</th><th>n</th></tr></thead><tbody>' +
      body + '</tbody></table>';
  }

  function renderMethodology(methodology) {
    if (!methodology) return '';
    var sources = methodology.sources || [];
    var metrics = methodology.metrics || [];
    var srcHtml = sources.map(function (s) {
      return '<li><a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.citation) + '</a>' +
        '<span class="backtest-method__topic">' + esc(s.topic || '') + '</span></li>';
    }).join('');
    var metricHtml = metrics.map(function (m) {
      var links = (m.sources || []).map(function (s) {
        return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.id || 'source') + '</a>';
      }).join(', ');
      return '<div class="backtest-method__metric"><strong>' + esc(m.label) + '</strong>' +
        '<code class="backtest-method__formula">' + esc(m.formula) + '</code>' +
        '<p>' + esc(m.definition) + '</p>' +
        (m.coverage ? '<p class="backtest-method__cov">' + esc(m.coverage) + '</p>' : '') +
        (links ? '<p class="backtest-method__refs">Sources: ' + links + '</p>' : '') +
        '</div>';
    }).join('');
    return '<details class="backtest-method card" open>' +
      '<summary>Methodology &amp; sources (selective classification / meta-labeling)</summary>' +
      '<p class="backtest-method__summary">' + esc(methodology.summary || '') + '</p>' +
      '<div class="backtest-method__grid">' + metricHtml + '</div>' +
      '<h4 class="backtest-method__h">References</h4><ul class="backtest-method__refs-list">' + srcHtml + '</ul>' +
      '</details>';
  }

  function renderEndorsementOverlap(overlap) {
    if (!overlap || !overlap.sample_size) return '';
    var uni = overlap.unanimous || {};
    var html = '<details class="backtest-overlap card" open>' +
      '<summary>Do the judges agree on the same picks?</summary>' +
      '<p class="backtest-overlap__intro">Overlap uses the same endorsement rules as the hit-rate KPIs above (score ≥ τ).</p>';

    if (uni.n != null && overlap.sample_size) {
      var uniHit = uni.hit_rate != null ? pctLabel(uni.hit_rate) : '—';
      html += '<p class="backtest-overlap__unanimous"><strong>All three said yes:</strong> ' +
        uni.n + '/' + overlap.sample_size +
        (uni.pct != null ? ' (' + uni.pct + '%)' : '') +
        ' · hit rate when unanimous: ' + uniHit + '</p>';
    }

    html += '<table class="tbl tbl--compact backtest-overlap__table"><thead><tr>' +
      '<th>Pair</th><th>Both endorse</th><th>% of sample</th><th>When A says yes, B also</th></tr></thead><tbody>';
    (overlap.pairs || []).forEach(function (row) {
      var ab = row.pct_of_a != null ? (row.pct_of_a + '% of ' + esc((overlap.judges[row.a] || {}).label || row.a)) : '—';
      html += '<tr><td>' + esc(row.label || '') + '</td>' +
        '<td class="mono">' + (row.both_n != null ? row.both_n : '—') + '</td>' +
        '<td class="mono">' + (row.both_pct != null ? row.both_pct + '%' : '—') + '</td>' +
        '<td class="mono">' + ab + '</td></tr>';
    });
    html += '</tbody></table>';

    if (overlap.snapshot_missing_pct != null) {
      html += '<p class="backtest-overlap__meta">Subnet snapshots missing on ' +
        overlap.snapshot_missing_pct + '% of picks in this window.</p>';
    }

    var notes = (overlap.health && overlap.health.notes) || [];
    if (notes.length) {
      html += '<ul class="backtest-overlap__notes">';
      notes.forEach(function (note) {
        var cls = note.level === 'warning' ? ' backtest-overlap__note--warning' : '';
        html += '<li class="backtest-overlap__note' + cls + '">' + esc(note.text || '') + '</li>';
      });
      html += '</ul>';
    }
    html += '</details>';
    return html;
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
    var councilRate = council.win_rate;
    var sample = payload.sample_size || 0;
    var html = '';
    if (councilRate != null && sample > 0) {
      var pct = Math.round(Number(councilRate) * 1000) / 10;
      html +=
        '<div class="backtest-meter card" role="status">' +
        '<div class="backtest-meter__label">Council direction rate</div>' +
        '<div class="backtest-meter__val">' + pct + '%</div>' +
        '<div class="backtest-meter__bar"><div class="backtest-meter__fill" style="width:' + Math.min(pct, 100) + '%;"></div></div>' +
        '<div class="backtest-meter__sub">n=' + sample + ' graded · coverage 100%</div></div>';
    }
    html += '<div class="kpi-strip">' +
      '<div class="kpi card"><div class="lbl">Council</div><div class="v">' + pctLabel(council.win_rate) + '</div>' +
      '<div class="sub">n=' + (payload.sample_size || 0) + ' · coverage ' +
      (council.coverage_pct != null ? council.coverage_pct + '%' : '100%') + '</div></div>';
    ['oracle', 'echo', 'pulse'].forEach(function (name) {
      var judge = judges[name] || {};
      var filtered = judge.filtered || {};
      var rate = filtered.win_rate != null ? filtered.win_rate : judge.win_rate;
      var n = filtered.n != null ? filtered.n : judge.endorsed_n;
      var cov = judge.coverage_pct != null ? judge.coverage_pct : filtered.coverage_pct;
      var th = filtered.min_score != null ? filtered.min_score : judge.threshold;
      var label = name.charAt(0).toUpperCase() + name.slice(1);
      html += '<div class="kpi card"><div class="lbl">' + label + '</div><div class="v">' + pctLabel(rate) + '</div>' +
        '<div class="sub">n=' + (n != null ? n : '—') +
        (cov != null ? ' · coverage ' + cov + '%' : '') +
        (th != null ? ' · τ≥' + th : '') +
        ' · avg pnl ' + fmt(judge.avg_pnl_pct) + '%</div></div>';
    });
    html += '</div>';

    html += renderEndorsementOverlap(payload.endorsement_overlap);

    html += '<div class="backtest-panels">';
    ['oracle', 'echo', 'pulse'].forEach(function (name) {
      var judge = judges[name] || {};
      var label = name.charAt(0).toUpperCase() + name.slice(1);
      html += '<div class="backtest-panel card">' +
        '<h3 class="backtest-panel__title">' + label + ' calibration</h3>' +
        '<p class="backtest-panel__hint">Reliability diagram — observed hit-rate per score bin (Murphy 1973)</p>' +
        renderCalibrationChart(name, judge.calibration) +
        '<h4 class="backtest-panel__subtitle">Risk–coverage (τ)</h4>' +
        '<p class="backtest-panel__hint">Hit-rate and coverage at score thresholds (El-Yaniv &amp; Wiener 2010)</p>' +
        renderRiskCoverageTable(judge.risk_coverage) +
        '</div>';
    });
    html += '</div>';

    html += renderMethodology(payload.methodology);
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

  function episodeKindLabel(kind) {
    var map = {
      origin: 'Starting point',
      subnet_divergence: 'Reality check',
      weight_nudge: 'Dial adjustment',
      calibration: 'Calibration',
      version_upgrade: 'Version upgrade',
      version_nickname: 'Unofficial promotion',
      current: 'Today'
    };
    return map[kind] || String(kind || '').replace(/_/g, ' ');
  }

  function renderFormulaLineage(catalog) {
    var root = document.getElementById('formula-lineage-root');
    if (!root) return;
    if (!catalog || catalog.status !== 'ok' || !(catalog.lanes || []).length) {
      root.innerHTML = '';
      return;
    }
    var html = '<details class="formula-lineage card" open>' +
      '<summary>Where each voice comes from</summary>' +
      '<p class="formula-lineage__intro">' + esc(catalog.summary || '') + '</p>';
    catalog.lanes.forEach(function (lane) {
      var formula = lane.current_formula || {};
      var loop = lane.learning_loop || {};
      var insp = (lane.inspiration || []).map(function (s) {
        return '<li><a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' +
          esc(s.citation) + '</a>' +
          (s.relationship ? ' <span class="formula-lineage__rel">(' + esc(s.relationship) + ')</span>' : '') +
          (s.note ? '<span class="formula-lineage__note">' + esc(s.note) + '</span>' : '') +
          '</li>';
      }).join('');
      var adap = (lane.adaptations || []).map(function (a) {
        return '<li>' + esc(a) + '</li>';
      }).join('');
      var weight = loop.current_weight != null ? loop.current_weight : '—';
      var acc = loop.accuracy != null ? pctLabel(loop.accuracy) : '—';
      var councilVer = loop.council_weights_version ? (' · council v' + loop.council_weights_version) : '';
      var scoreVer = loop.scoring_version ? (' · scoring v' + loop.scoring_version) : '';
      html += '<article class="formula-lineage__lane" id="lineage-' + esc(lane.id) + '">' +
        '<h4 class="formula-lineage__lane-title">' + esc(lane.label) + '</h4>' +
        '<code class="formula-lineage__expr">' + esc(formula.expression || '') + '</code>' +
        '<p class="formula-lineage__impl">' + esc(formula.summary || '') + '</p>' +
        '<p class="formula-lineage__live"><strong>Live weight</strong> ' + weight +
        ' · <strong>hit rate</strong> ' + acc +
        (loop.graded_n ? ' (' + loop.graded_n + ' picks)' : '') +
        councilVer + scoreVer + '</p>' +
        '<p class="formula-lineage__loop-note">' + esc(loop.stagnant_source_note || '') + '</p>' +
        '<h5 class="formula-lineage__sub">Where the idea came from</h5><ul>' + insp + '</ul>' +
        '<h5 class="formula-lineage__sub">What we changed</h5><ul>' + adap + '</ul>' +
        '</article>';
    });
    html += '</details>';
    root.innerHTML = html;
  }

  function renderEvolutionTrail(trail) {
    var root = document.getElementById('formula-evolution-root');
    if (!root) return;
    if (!trail || trail.status !== 'ok' || !(trail.trail || []).length) {
      root.innerHTML = '';
      return;
    }
    var html = '<details class="formula-evolution card" open>' +
      '<summary>The story so far — ' + esc(trail.label || trail.lane_id) + '</summary>' +
      '<p class="formula-evolution__intro">' + esc(trail.summary || '') + '</p>' +
      '<ol class="formula-evolution__timeline">';
    trail.trail.forEach(function (ep) {
      var range = (ep.from && ep.to && ep.from !== ep.to) ? (ep.from + ' → ' + ep.to) : (ep.from || ep.to || '');
      var div = ep.divergence_pct != null ? (' · shift ' + ep.divergence_pct + '%') : '';
      var kindLabel = episodeKindLabel(ep.kind);
      if (ep.version) {
        kindLabel += ' v' + ep.version;
      }
      html += '<li class="formula-evolution__episode formula-evolution__episode--' + esc(ep.kind || 'event') + '">' +
        '<div class="formula-evolution__meta"><span class="formula-evolution__kind">' + esc(kindLabel) + '</span>' +
        '<span class="formula-evolution__range">' + esc(range) + div + '</span></div>' +
        '<p class="formula-evolution__narrative">' + esc(ep.narrative || '') + '</p>';
      if (ep.nickname) {
        html += '<p class="formula-evolution__nickname">「 ' + esc(ep.nickname) + ' 」</p>';
      }
      if (ep.paper_twist) {
        html += '<p class="formula-evolution__paper-twist">';
        if (ep.paper_title) {
          html += 'Twist on <em>' + esc(ep.paper_title) + '</em>: ';
        }
        html += '「 ' + esc(ep.paper_twist) + ' 」</p>';
      }
      if (ep.formula_expression) {
        html += '<code class="formula-evolution__expr">' + esc(ep.formula_expression) + '</code>';
      }
      if ((ep.trigger_subnets || []).length) {
        html += '<ul class="formula-evolution__subnets">';
        ep.trigger_subnets.forEach(function (sn) {
          var pred = sn.predicted_pct != null ? fmtSigned(sn.predicted_pct) : '—';
          var act = sn.actual_pct != null ? fmtSigned(sn.actual_pct) : '—';
          html += '<li><strong>' + esc(sn.name || ('SN' + sn.netuid)) + '</strong> expected ' +
            esc(sn.expected_direction || '?') + ' (' + pred + ') · actual ' + act +
            (sn.correct === false ? ' <span class="neg">miss</span>' : '') +
            (sn.correct === true ? ' <span class="pos">hit</span>' : '') + '</li>';
        });
        html += '</ul>';
      }
      if (ep.weight_before != null && ep.weight_after != null) {
        html += '<p class="formula-evolution__weight">Weight ' + ep.weight_before + ' → ' + ep.weight_after + '</p>';
      }
      html += '</li>';
    });
    html += '</ol></details>';
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
    patchDataFreshnessFromSubnetMeta(subnets, meta);
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
      var wrap = canvas.closest('.chart-canvas-wrap');
      if (wrap) wrap.classList.add('chart-canvas-wrap--radar');
      return;
    }
    var ranked = subnets.slice().sort(function (a, b) {
      return (Number(b.emission) || 0) - (Number(a.emission) || 0);
    }).slice(0, 3);
    var legend = ranked.map(function (sn, idx) {
      var nu = subnetNetuid(sn);
      var em = Number(sn.emission) || 0;
      var chg = Number(sn.price_change_24h) || 0;
      var mom = Math.min(50 + chg * 2, 100);
      var barClass = chg >= 0 ? 'radar-item__bar--up' : 'radar-item__bar--down';
      return (
        '<div class="radar-item radar-item--enter' +
        (idx === 0 ? ' radar-item--lead' : '') +
        '" style="--radar-i:' +
        idx +
        '"><div class="name">' +
        esc(subnetName(sn)) +
        '</div><div class="meta">emission ' +
        fmt(em, 2) +
        ' · 24h ' +
        fmtSigned(chg) +
        '</div><div class="radar-item__track" aria-hidden="true"><div class="radar-item__bar ' +
        barClass +
        '" style="width:' +
        mom +
        '%"></div></div></div>'
      );
    }).join('');
    var html =
      '<div class="card momentum-grid"><div class="card"><div class="card-head"><h3>Subnet Radar</h3>' +
      '<span class="src-tag">top 3 · canvas</span></div><div class="chart-box"><div class="chart-canvas-wrap chart-canvas-wrap--radar">' +
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
  var cockpitPicksConnected = false;
  var lastPicksEmittedAt = 0;

  function applyPicksSnapshot(payload) {
    if (!payload || payload.type !== 'cockpit.picks') return;
    lastPicksEmittedAt = Date.now();
    cockpitPicksConnected = true;
    var hourPicks = (payload.hour && payload.hour.picks) || [];
    var dayPick = payload.day && payload.day.pick;
    var dayPicks = dayPick ? [dayPick] : [];
    if (payload.day && payload.day.candidate && !dayPick) {
      dayPicks = [payload.day.candidate];
    }
    renderHourDayPicks(hourPicks, dayPicks);
    if (window.HourWatchUI && window.HourWatchUI.patchHourWatch) {
      window.HourWatchUI.patchHourWatch(payload);
    }
    if (window.HomeHydrateCache) {
      window.HomeHydrateCache.hourPicks = hourPicks;
      window.HomeHydrateCache.dayPick = payload.day || null;
      window.HomeHydrateCache.picksEmittedAt = payload.emitted_at;
      window.HomeHydrateCache.at = Date.now();
    }
    document.dispatchEvent(new CustomEvent('home:cockpit-picks', { detail: payload }));
  }

  function connectCockpitStream() {
    if (cockpitStream || typeof EventSource === 'undefined') return;
    if (!document.querySelector('[data-home-live]') && !document.querySelector('.cockpit-card[data-section-id]')) return;
    cockpitStream = new EventSource('/api/cockpit/stream');
    cockpitStream.addEventListener('cockpit.picks', function (ev) {
      try {
        applyPicksSnapshot(JSON.parse(ev.data));
      } catch (e) {
        console.warn('[cockpit_hydrate] picks SSE parse failed', e);
      }
    });
    cockpitStream.addEventListener('cockpit.sections', function (ev) {
      try {
        var payload = JSON.parse(ev.data);
        if (payload && payload.sections) {
          renderCockpitSections(payload.sections);
        }
        if (!cockpitPicksConnected || Date.now() - lastPicksEmittedAt > 5000) {
          document.dispatchEvent(new CustomEvent('home:cockpit-tick'));
        }
      } catch (e) {
        console.warn('[cockpit_hydrate] SSE parse failed', e);
      }
    });
    cockpitStream.onerror = function () {
      console.warn('[cockpit_hydrate] SSE disconnect; keeping last snapshot');
    };
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden' && cockpitStream) {
        cockpitStream.close();
        cockpitStream = null;
        cockpitPicksConnected = false;
      } else if (document.visibilityState === 'visible' && !cockpitStream) {
        connectCockpitStream();
      }
    });
  }

  function pause(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  var SUBNET_FIELDS = 'id,netuid,name,price_change_24h,apy,staking_data,total_stake,stake,emission,source,live,sources';

  function storyStripUrl() {
    var f = window.LivingFocus && window.LivingFocus.netuid;
    return f != null ? '/api/story-strip?focus=' + encodeURIComponent(f) : '/api/story-strip';
  }

  async function refreshStoryStrip() {
    try {
      var strip = await fetchJsonRetry(storyStripUrl(), 22000, 2);
      if (window.HomeLiveRefresh && window.HomeLiveRefresh.patchStoryStrip) {
        window.HomeLiveRefresh.patchStoryStrip(strip);
      }
    } catch (e) {
      console.warn('[cockpit_hydrate] story-strip refresh failed', e);
    }
  }

  function startTrailHydration() {
    return fetchJsonRetry('/api/mindmap/trail?limit=20', 15000, 1)
      .then(function (payload) {
        var next = safePayload(payload).trail || [];
        renderTrail(next);
        patchK3LifecycleFromTrail(next, lastDailyPickPayload);
        window.__homeTrailHydratePending = false;
        window.HomeHydrateCache = window.HomeHydrateCache || {};
        window.HomeHydrateCache.trail = next;
        window.HomeHydrateCache.at = Date.now();
        document.dispatchEvent(new CustomEvent('home:trail-hydrated', {
          detail: { trail: next },
        }));
        return next;
      })
      .catch(function (err) {
        window.__homeTrailHydratePending = false;
        console.warn('[cockpit_hydrate] trail fetch failed', err);
        return [];
      });
  }

  async function run() {
    // #region agent log
    debugHydration('A', 'cockpit hydrate run entry', {
      hydrate: document.documentElement.dataset.hydrate || null,
      hero: !!document.getElementById('tribunal-hero'),
      readyState: document.readyState,
    });
    // #endregion
    if (document.documentElement.dataset.hydrate !== '1') return;
    showHydrateSkeletons();
    // H1: hour-watch rib via cockpit.picks — connect before deferred tier-3 panels
    connectCockpitStream();

    var stats = null;
    var subnets = [];
    var subnetsMeta = {};
    var hourPicks = [];
    var dayPicks = [];
    var trail = [];
    // Start independently of the tier-1 burst. A slow daily/council request
    // must not leave a real trail hidden behind its SSR placeholder.
    window.__homeTrailHydratePending = true;
    var trailPromise = startTrailHydration();

    try {
      // Tier 1 — start every critical request together. Previously the daily
      // pick blocked pump, roster, learning, and story hydration in a serial
      // waterfall; one slow council scorer could leave the whole page below
      // the Telegram desk looking frozen.
      // Tier 1a — daily call first (parallel request; legacy marker)
      var dailyPickRequest = fetchJsonRetry('/api/daily-pick', 35000, 3)
        .then(function (dpResult) {
          // #region agent log
          debugHydration('C', 'daily pick fetch resolved in browser', {
            status: dpResult && dpResult.status || null,
            action: dpResult && dpResult.action || null,
            hasPick: !!(dpResult && dpResult.pick),
            hasCandidate: !!(dpResult && dpResult.candidate),
          });
          // #endregion
          renderDailyPick(dpResult);
          // Make the Daily Call immediately reusable by SSE / hot-refresh
          // listeners instead of leaving a race window before tier-2 completes.
          window.HomeHydrateCache = window.HomeHydrateCache || {};
          window.HomeHydrateCache.dailyPick = lastDailyPickPayload;
          window.HomeHydrateCache.at = Date.now();
          prefetchFocusJudges(dpResult);
          return dpResult;
        })
        .catch(function (e) {
          // #region agent log
          debugHydration('C', 'daily pick fetch rejected in browser', {
            errorType: e && e.name || 'Error',
          });
          // #endregion
          console.warn('[cockpit_hydrate] daily-pick fetch failed', e);
          markSectionFailed('section-daily-pick', 'Quiet — daily call delayed. Retry when /api/daily-pick responds.');
          return null;
        })
        // catch (e) is intentionally isolated from the parallel tier.
        .then(function (dpResult) {
          hydrateWeighedAlternatives(dpResult && dpResult.shortlist);
          return dpResult;
        });

      // Tier 1b — pump desk (parallel request)
      var pumpAlertsRequest = fetchJsonRetry('/api/pump-alerts', 12000, 2)
        .then(function (pumpPayload) {
          renderPumpAlerts(pumpPayload);
          return pumpPayload;
        })
        .catch(function (e) {
          console.warn('[cockpit_hydrate] pump-alerts fetch failed', e);
          var pumpHost = document.getElementById('pump-alert-body');
          if (pumpHost && !pumpHost.querySelector('.pump-desk__row')) {
            pumpHost.innerHTML =
              '<p class="pump-desk__empty">Quiet — lead scanner API slow. SSR snapshot stays until refresh succeeds.</p>';
          }
          return null;
        });

      // This batch is intentionally independent of both hero requests.
      var tierBatchPromise = Promise.allSettled([
        fetchJsonRetry(
          '/api/subnets?fields=' + encodeURIComponent(SUBNET_FIELDS),
          28000,
          2
        ),
        loadLearningStats(),
        fetchJsonRetry(storyStripUrl(), 22000, 2).then(function (strip) {
          if (window.HomeLiveRefresh && window.HomeLiveRefresh.patchStoryStrip) {
            window.HomeLiveRefresh.patchStoryStrip(strip);
          }
        })
      ]);
      var tierBatch = await tierBatchPromise;

      // Keep promise rejections observed even when a slow hero request
      // resolves after the rest of the homepage has already painted.
      Promise.allSettled([dailyPickRequest, pumpAlertsRequest]).catch(function () {});

      if (tierBatch[0].status === 'fulfilled') {
        var subPayload = safePayload(tierBatch[0].value);
        subnets = subPayload.subnets || [];
        subnetsMeta = subPayload.meta || {};
        indexRegistry(subnets);
        renderHero(subnets, subnetsMeta);
        patchDataFreshnessFromSubnetMeta(subnets, subnetsMeta);
      } else {
        console.warn('[cockpit_hydrate] subnets fetch failed', tierBatch[0].reason);
      }

      if (tierBatch[1].status === 'fulfilled' && tierBatch[1].value) {
        stats = tierBatch[1].value;
        renderKpi(stats);
        renderCouncilWeights(
          stats.expert_weights || {},
          stats.expert_weight_deltas || {},
          stats.expert_graded_counts || {}
        );
        if (document.getElementById('tribunal-hero')) {
          if (lastDailyPickPayload) {
            renderTribunalHero(lastDailyPickPayload, stats);
          } else {
            patchTribunalJudges(stats, {});
            patchTribunalPanels({}, stats);
            patchTribunalInstrument(stats, {});
            patchTribunalEyeArcs(stats.judge_weights);
          }
        }
        if (stats.trust_banner && window.SimiTrustBanner && window.SimiTrustBanner.render) {
          window.SimiTrustBanner.render(stats.trust_banner);
        }
        fetchJsonRetry('/api/message-intel?limit=1', 12000, 1)
          .then(function (mi) {
            syncProofEvidencePanels(stats.trust_banner, {
              telegram_proof: (mi && mi.meta && mi.meta.telegram_proof) || {},
              working_count:
                stats.working && stats.working.top_price_signals
                  ? stats.working.top_price_signals.length
                  : null,
              council_pending: stats.council_pending,
              pump_pending: stats.pump_pending,
              alignment_diagnostic_events: stats.alignment_diagnostic_events,
            });
          })
          .catch(function () {});
        fetchJsonRetry('/api/ops/evidence', 12000, 1)
          .then(function (evidence) {
            syncAccuracyLiftPanel(evidence && evidence.accuracy_lift);
          })
          .catch(function () {});
      } else {
        markSectionFailed('section-kpi', 'Quiet — learning stats unavailable. KPIs stay on last SSR snapshot.');
        markSectionFailed('section-council', 'Quiet — council weights unavailable. Expert cards stay on last SSR snapshot.');
      }

      // Tier 2 — secondary panels start only after the critical dashboard path
      // paints, so a slow council/portfolio provider cannot hold the whole site.
      setTimeout(function () {
        Promise.allSettled([
          fetchJsonRetry('/api/simivision', 16000, 1).then(function (payload) {
            var data = safePayload(safePayload(payload).data);
            renderSimivision(data.top || [], data.meta || {});
          }),
          window.PaperPortfolio && window.PaperPortfolio.hydrate
            ? window.PaperPortfolio.hydrate()
            : fetchJsonRetry('/api/portfolio/status', 15000, 1),
          window.BrainLetter && window.BrainLetter.hydrate
            ? window.BrainLetter.hydrate()
            : fetchJsonRetry('/api/letter/brain', 10000, 0)
        ]).catch(function () {});
      }, 350);

      renderFooterStatus({
        dataSource: subnetsMeta.source,
        meta: subnetsMeta,
        subnets: subnets.length,
        trail: null,
        predictions: stats && stats.total_records != null ? stats.total_records : null,
      });

      window.HomeHydrateCache = {
        dailyPick: lastDailyPickPayload,
        simivision: lastSimivisionTop ? { top: lastSimivisionTop, meta: lastSimivisionMeta } : null,
        trail: (window.HomeHydrateCache && window.HomeHydrateCache.trail) || null,
        subnets: subnets,
        subnetsMeta: subnetsMeta,
        at: Date.now(),
      };
      document.dispatchEvent(new CustomEvent('home:hydrate-cache', {
        detail: window.HomeHydrateCache,
      }));
      clearShellWarming();
      clearHydrateFlag();

      console.log('[cockpit_hydrate] tier-1/2 panels updated');

      // Tier 3 — warehouse panels (deferred so tier 1 wins CPU on Fly)
      scheduleDeferred(function () {
        runDeferredPanels(stats, subnets, subnetsMeta, hourPicks, dayPicks, trail, trailPromise);
      }, 450);
    } catch (e) {
      console.error('[cockpit_hydrate] fatal', e);
      clearHydrateFlag();
    }
  }

  async function runDeferredPanels(stats, subnets, subnetsMeta, hourPicks, dayPicks, trail, trailPromise) {
    try {
      if (window.SimiMarketDrivers && window.SimiMarketDrivers.refresh) {
        window.SimiMarketDrivers.refresh();
      }

      // Guard pre-trail renders so a single panel failure can't abort the whole
      // deferred chain and leave below-fold panels + the footer Trail metric stuck.
      if (subnets.length) {
        try {
          renderStaking(subnets);
        } catch (e) { console.warn('[cockpit_hydrate] renderStaking failed', e); }
        try {
          renderUndervalued(subnets);
        } catch (e) { console.warn('[cockpit_hydrate] renderUndervalued failed', e); }
        try {
          renderRadar(subnets);
        } catch (e) { console.warn('[cockpit_hydrate] renderRadar failed', e); }
      }

      // Reuse the request started during tier 1; never issue a second trail
      // request just because the warehouse pass began later.
      try {
        trail = trailPromise ? await trailPromise : await startTrailHydration();
        patchK3LifecycleFromTrail(trail, lastDailyPickPayload);
        // Refresh the footer Trail metric as soon as the trail fetch lands, not
        // only at the end of the deferred chain (which waits on 30s picks).
        renderFooterStatus({
          dataSource: subnetsMeta.source,
          meta: subnetsMeta,
          subnets: subnets.length,
          trail: trail.length,
          predictions: stats && stats.total_records != null ? stats.total_records : null,
        });
        if (window.HomeHydrateCache) {
          window.HomeHydrateCache.trail = trail;
          window.HomeHydrateCache.at = Date.now();
        }
        document.dispatchEvent(new CustomEvent('home:hydrate-trail', { detail: { trail: trail } }));
      } catch (e) {
        console.warn('[cockpit_hydrate] trail fetch failed', e);
      } finally { window.__homeTrailHydratePending = false; }

      // Warehouse panels do not depend on each other. Start them together so
      // a slow picks or indicators endpoint cannot hold signals, alerts,
      // cockpit summaries, and replay evidence behind it.
      var picksRequest = fetchJsonRetry('/api/top-picks', 30000, 1).catch(function () { return null; });
      var indicatorsRequest = fetchJsonRetry('/api/indicators-convergence', 15000, 1).catch(function (e) {
        console.warn('[cockpit_hydrate] indicators fetch failed', e);
        return null;
      });
      var signalsRequest = Promise.allSettled([
        fetchJsonRetry('/api/signals?refresh=false', 15000, 1),
        fetchJsonRetry('/api/alerts?refresh_checks=false', 12000, 1).catch(function () { return null; }),
        fetchJsonRetry('/api/signals/summary', 12000, 1).catch(function () { return null; }),
      ]);
      var sectionsRequest = fetchJsonRetry('/api/cockpit/sections', 20000, 1).catch(function (e) {
        console.warn('[cockpit_hydrate] cockpit sections fetch failed', e);
        return null;
      });
      var backtestRequest = Promise.allSettled([
        fetchJsonRetry('/api/backtest?limit=120', 18000, 1),
        fetchJsonRetry('/api/formula-lineage', 12000, 1),
        fetchJsonRetry('/api/formula-lineage/dark_horse/evolution', 12000, 1),
      ]);

      // Paint each lower panel from its own promise. Do not await top-picks
      // here: that endpoint may legitimately time out while signals, alerts,
      // sections, and replay evidence are already available.
      picksRequest.then(function (pickPayload) {
        pickPayload = safePayload(pickPayload);
        if (pickPayload && Object.keys(pickPayload).length && !cockpitPicksConnected) {
          hourPicks = pickPayload.hour_picks || [];
          dayPicks = pickPayload.day_picks || [];
          renderHourDayPicks(hourPicks, dayPicks);
          updateGroupData(hourPicks, dayPicks, trail, subnets);
          paintCharts();
          return;
        }
        if (cockpitPicksConnected) return;
        return Promise.all([
          fetchJsonRetry('/api/top-pick/hour', 18000, 1),
          fetchJsonRetry('/api/top-pick/day', 18000, 1),
        ]).then(function (fallback) {
          hourPicks = safePayload(fallback[0]).picks || [];
          dayPicks = safePayload(fallback[1]).picks || [];
          renderHourDayPicks(hourPicks, dayPicks);
          updateGroupData(hourPicks, dayPicks, trail, subnets);
          paintCharts();
        });
      }).catch(function (e) {
        console.warn('[cockpit_hydrate] pick fallback failed', e);
        markSectionFailed('section-picks', 'Quiet — horizon picks timed out. Open Pro cockpit again after /api/top-picks responds.');
      });

      indicatorsRequest.then(function (indPayload) {
        if (indPayload) renderIndicators(safePayload(indPayload).subnets || []);
      }).catch(function (e) {
        console.warn('[cockpit_hydrate] indicators render failed', e);
      });

      signalsRequest.then(function (results) {
        if (results[0].status === 'fulfilled' || results[1].status === 'fulfilled' || results[2].status === 'fulfilled') {
          var sigPayload = results[0].status === 'fulfilled' ? safePayload(results[0].value) : {};
          var alertsPayload = results[1].status === 'fulfilled' ? safePayload(results[1].value) : {};
          var summaryPayload = results[2].status === 'fulfilled' ? results[2].value : null;
          if (summaryPayload && summaryPayload.total_subnets != null && typeof window.__renderSignalSummary === 'function') {
            window.__renderSignalSummary(summaryPayload);
          }
          if (typeof window.__applySignalsPayload === 'function') {
            window.__applySignalsPayload(sigPayload.signals || [], (alertsPayload.alerts) || []);
          } else {
            renderSignals(sigPayload.signals || [], (alertsPayload.alerts) || []);
          }
        }
      }).catch(function (e) {
        console.warn('[cockpit_hydrate] signals panels failed', e);
      });

      sectionsRequest.then(function (sectionsPayload) {
        if (sectionsPayload) renderCockpitSections(safePayload(sectionsPayload).sections || []);
      }).catch(function (e) {
        console.warn('[cockpit_hydrate] cockpit sections render failed', e);
      });

      updateGroupData(hourPicks, dayPicks, trail, subnets);
      paintCharts();
      renderFooterStatus({
        dataSource: subnetsMeta.source,
        meta: subnetsMeta,
        subnets: subnets.length,
        trail: trail.length,
        predictions: stats && stats.total_records != null ? stats.total_records : null,
      });

      window.HomeHydrateCache = {
        dailyPick: lastDailyPickPayload,
        simivision: lastSimivisionTop ? { top: lastSimivisionTop, meta: lastSimivisionMeta } : null,
        trail: trail,
        subnets: subnets,
        subnetsMeta: subnetsMeta,
        at: Date.now(),
      };
      document.dispatchEvent(new CustomEvent('home:hydrate-cache', {
        detail: window.HomeHydrateCache,
      }));

      connectCockpitStream();

      backtestRequest.then(function (trio) {
        if (trio.every(function (item) { return item.status === 'fulfilled'; })) {
          renderBacktest(trio[0].value);
          renderFormulaLineage(trio[1].value);
          renderEvolutionTrail(trio[2].value);
        } else {
          console.warn('[cockpit_hydrate] backtest fetch failed', trio);
          var btRoot = document.getElementById('backtest-panel-root');
          if (btRoot && btRoot.querySelector('.empty')) {
            btRoot.innerHTML = '<p class="empty empty--quiet">Quiet — backtest replay unavailable right now. Resolved predictions populate this panel when the API responds.</p>';
          }
        }
      }).catch(function (e) {
        console.warn('[cockpit_hydrate] backtest render failed', e);
      });

      console.log('[cockpit_hydrate] deferred panels updated');
    } catch (e) {
      console.warn('[cockpit_hydrate] deferred tier failed', e);
      window.__homeTrailHydratePending = false;
    }
  }

  function bindProofTabs() {
    var tabs = document.querySelectorAll('.proof-band__tab[data-proof-tab]');
    if (!tabs.length) return;
    tabs.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-proof-tab');
        tabs.forEach(function (b) {
          var on = b.getAttribute('data-proof-tab') === target;
          b.classList.toggle('proof-band__tab--active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        var council = document.getElementById('proof-tab-council');
        var pump = document.getElementById('proof-tab-pump');
        var hero = document.getElementById('proof-band-score-hero');
        if (council) council.hidden = target !== 'council';
        if (pump) pump.hidden = target !== 'pump';
        if (hero) hero.hidden = target === 'pump';
      });
    });
  }

  document.addEventListener('living-focus:change', function () {
    refreshStoryStrip();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      maybeClearShellWarmingEarly();
      bindProofTabs();
      patchK3StaleBadge();
      run();
    });
  } else {
    maybeClearShellWarmingEarly();
    bindProofTabs();
    patchK3StaleBadge();
    run();
  }

  // ---------- Council Hero v4 (tribunal hero slot) ----------

  function formatGaugePct(val) {
    if (val == null || isNaN(Number(val))) return '—';
    var n = Number(val);
    if (Math.abs(n - Math.round(n)) < 0.05) return String(Math.round(n)) + '%';
    return n.toFixed(1) + '%';
  }

  function judgeSignalPct(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var v = raw.confidence != null ? raw.confidence : raw.score;
    if (v == null || isNaN(Number(v))) return null;
    var n = Number(v);
    return n <= 1 ? n * 100 : n;
  }

  function judgeSignalsFromDom() {
    var hero = document.getElementById('tribunal-hero');
    if (!hero) return null;
    var out = { oracle: null, echo: null, pulse: null };
    var used = false;
    hero.querySelectorAll('[data-judge]').forEach(function (seat) {
      var key = seat.getAttribute('data-judge');
      var signalEl = seat.querySelector('[data-judge-signal]');
      if (!key || !signalEl) return;
      var txt = String(signalEl.textContent || '').trim().replace('%', '');
      if (!txt || txt === '—') return;
      var n = Number(txt);
      if (isNaN(n)) return;
      out[key] = n;
      used = true;
    });
    return used ? out : null;
  }

  function judgeSignalsFromPick(payload) {
    var active = (payload && (payload.pick || payload.candidate)) || {};
    var scores = active.judge_scores_at_creation;
    var out = { oracle: null, echo: null, pulse: null };
    if (scores && typeof scores === 'object') {
      ['oracle', 'echo', 'pulse'].forEach(function (key) {
        out[key] = judgeSignalPct(scores[key]);
      });
    }
    var hasSignal = ['oracle', 'echo', 'pulse'].some(function (key) {
      return out[key] != null && !isNaN(Number(out[key]));
    });
    if (!hasSignal) {
      var dom = judgeSignalsFromDom();
      if (dom) return dom;
    }
    return out;
  }

  function weightedVerdictPct(weights, signals) {
    if (!weights || !signals) return null;
    var total = 0;
    var used = false;
    ['oracle', 'echo', 'pulse'].forEach(function (key) {
      var w = weights[key];
      var s = signals[key];
      if (w == null || s == null || isNaN(Number(w)) || isNaN(Number(s))) return;
      total += Number(w) * Number(s);
      used = true;
    });
    if (!used) return null;
    return Math.round(total * 10) / 10;
  }

  function tribunalGaugePct(dailyPick, learningStats) {
    var weights = (learningStats && learningStats.judge_weights) || {};
    var signals = judgeSignalsFromPick(dailyPick);
    var weighted = weightedVerdictPct(weights, signals);
    if (weighted != null) return weighted;
    return tribunalConvictionPct(dailyPick);
  }

  function verdictKind(payload) {
    if (!payload) return 'cold';
    var act = String(payload.action || 'HOLD').toUpperCase();
    if (act === 'BUY') act = 'LONG';
    if (act === 'LONG' && pickIsPublishable(payload)) return 'sealed';
    if (payload.pick) return 'gated';
    if (!payload.pick && payload.candidate && act === 'HOLD') return 'gated';
    if (String(payload.status || '').toLowerCase() === 'pending') return 'forming';
    return 'cold';
  }

  var CONVICTION_WARM_PCT = 70;

  function convictionTemp(kind, gaugePct) {
    if (kind === 'cold' || kind === 'forming') return 'cool';
    if (kind === 'sealed') return 'warm';
    if (gaugePct == null || isNaN(Number(gaugePct))) return 'cool';
    return Number(gaugePct) >= CONVICTION_WARM_PCT ? 'warm' : 'cool';
  }

  function syncCouncilTemp(temp) {
    if (document.body) document.body.setAttribute('data-council-temp', temp);
  }

  function tribunalCenterLabel(payload, kind) {
    kind = kind || verdictKind(payload);
    var pills = tribunalVerdictPills(payload, kind);
    return pills.action ? pills.gate + ' · ' + pills.action : pills.gate;
  }

  function tribunalVerdictPills(payload, kind) {
    kind = kind || verdictKind(payload);
    if (kind === 'sealed') {
      var act = String(payload.action || 'LONG').toUpperCase();
      if (act === 'BUY') act = 'LONG';
      return { gate: 'SEALED', action: act };
    }
    if (kind === 'gated') return { gate: 'GATED', action: 'HOLD' };
    if (kind === 'forming') return { gate: 'FORMING', action: null };
    return { gate: 'COLD', action: null };
  }

  function tribunalConvictionPct(payload) {
    if (!payload) return null;
    var active = payload.pick || payload.candidate;
    if (!active) return null;
    var raw =
      active.final_confidence != null
        ? active.final_confidence
        : active.confidence != null
          ? active.confidence
          : active.conviction;
    if (raw == null || isNaN(Number(raw))) return null;
    var val = Number(raw);
    if (val <= 1) val *= 100;
    return Math.round(val);
  }

  function tribunalSubnetLabel(payload) {
    if (!payload) return 'Awaiting subnet';
    var active = payload.pick || payload.candidate;
    if (!active) return 'Awaiting subnet';
    var sn = active.subnet;
    if (!sn) return 'Awaiting subnet';
    var name = String(sn.name || '').trim();
    var netuid = sn.netuid;
    if (netuid == null) return name || '—';
    var snPrefix = 'SN' + netuid;
    if (!name || name.toUpperCase() === snPrefix.toUpperCase() || /^SN\d+$/i.test(name)) {
      return snPrefix;
    }
    return snPrefix + ' · ' + name;
  }

  function formatJudgeWeightPct(weight, weights) {
    if (weight == null || isNaN(Number(weight))) return '—';
    weights = weights || {};
    var vals = ['oracle', 'echo', 'pulse']
      .map(function (k) {
        return weights[k];
      })
      .filter(function (v) {
        return v != null && !isNaN(Number(v));
      })
      .map(Number);
    if (vals.length >= 2) {
      var spread = Math.max.apply(null, vals) - Math.min.apply(null, vals);
      if (spread < 0.015) return 'Equal weight';
    }
    var pct = Number(weight) * 100;
    if (Math.abs(pct - Math.round(pct)) < 0.05) return String(Math.round(pct)) + '%';
    return pct.toFixed(1) + '%';
  }

  function judgeAgreementLabels(signals) {
    signals = signals || {};
    var vals = ['oracle', 'echo', 'pulse']
      .map(function (k) {
        return signals[k];
      })
      .filter(function (v) {
        return v != null && !isNaN(Number(v));
      })
      .map(Number);
    if (vals.length < 2) return { consensus: '—', dissent: '—' };
    var spread = Math.max.apply(null, vals) - Math.min.apply(null, vals);
    var consensus =
      spread <= 10 ? 'High agreement' : spread <= 25 ? 'Moderate agreement' : 'Low agreement';
    var dissent;
    if (spread < 1) dissent = 'Unanimous';
    else if (spread >= 30) dissent = 'High dissent · ' + Math.round(spread) + ' pts';
    else dissent = Math.round(spread) + ' pt spread';
    return { consensus: consensus, dissent: dissent };
  }

  function patchTribunalEyeArcs(weights) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero) return;
    var outer = hero.querySelector('[data-eye-path]');
    var inner = hero.querySelector('[data-conviction-arc]');
    function placeOnPath(el, path, frac) {
      if (!el) return;
      if (path && path.getTotalLength) {
        var len = path.getTotalLength();
        if (len) {
          var t = ((frac % 1) + 1) % 1;
          var pt = path.getPointAtLength(t * len);
          el.setAttribute('cx', pt.x.toFixed(2));
          el.setAttribute('cy', pt.y.toFixed(2));
          return;
        }
      }
      var a = frac * Math.PI * 2 - Math.PI / 2;
      el.setAttribute('cx', (120 + 77.23 * Math.cos(a)).toFixed(2));
      el.setAttribute('cy', (70 + 42 * Math.sin(a)).toFixed(2));
    }
    function setArc(el, start, frac) {
      if (!el) return;
      var len = Math.max(0, Math.min(100, frac * 100));
      el.setAttribute('stroke-dasharray', len.toFixed(1) + ' ' + (100 - len).toFixed(1));
      el.setAttribute('stroke-dashoffset', (-start * 100).toFixed(1));
    }
    var p = parseFloat(hero.getAttribute('data-hero-conviction'));
    if (inner && isFinite(p)) {
      var c = Math.max(0, Math.min(100, p));
      inner.setAttribute('stroke-dasharray', c.toFixed(1) + ' ' + (100 - c).toFixed(1));
    }
    var present = weights && [weights.oracle, weights.echo, weights.pulse].every(function (x) {
      return typeof x === 'number' && isFinite(x);
    });
    if (!present) {
      hero.classList.add('tribunal-hero--consensus');
      placeOnPath(hero.querySelector('[data-comet]'), inner || outer, 0.25);
      return;
    }
    var total = weights.oracle + weights.echo + weights.pulse;
    var fracs = ['oracle', 'echo', 'pulse'].map(function (k) { return weights[k] / total; });
    var maxF = Math.max.apply(null, fracs);
    if (maxF - Math.min.apply(null, fracs) < 0.02) {
      hero.classList.add('tribunal-hero--consensus');
      placeOnPath(hero.querySelector('[data-comet]'), inner || outer, 0.25);
      return;
    }
    hero.classList.remove('tribunal-hero--consensus');
    var started = 0;
    ['oracle', 'echo', 'pulse'].forEach(function (k, i) {
      var f = fracs[i];
      setArc(hero.querySelector('[data-judge-arc="' + k + '"]'), started, f);
      placeOnPath(hero.querySelector('[data-rim-marker="' + k + '"]'), outer, started + f / 2);
      started += f;
    });
    placeOnPath(hero.querySelector('[data-comet]'), inner || outer, Math.min(0.99, (isFinite(p) ? p : 0) / 100));
  }

  function patchTribunalInstrument(stats, dailyPick) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero || !stats) return;
    function setM(k, v, arrow) {
      var el = hero.querySelector('[data-metric="' + k + '"]');
      if (!el || v == null || v === '') return;
      el.textContent = v;
      if (arrow) el.setAttribute('data-arrow', arrow);
      else el.removeAttribute('data-arrow');
    }
    function setMeter(k, pct) {
      var el = hero.querySelector('[data-metric="' + k + '"]');
      var bar = el && el.parentNode && el.parentNode.querySelector('.tribunal-hero__cell-meter i');
      if (bar && typeof pct === 'number' && isFinite(pct)) {
        bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
      }
    }
    var tb = stats.trust_banner || {};
    var graded = Number(tb.graded != null ? tb.graded : stats.graded) || 0;
    var correct = Number(tb.correct != null ? tb.correct : stats.correct) || 0;
    var wrong = Number(tb.wrong != null ? tb.wrong : stats.wrong) || 0;
    var acc = null;
    if (tb.ready && tb.accuracy != null && !isNaN(Number(tb.accuracy))) acc = Number(tb.accuracy) * 100;
    else if (graded > 0 && correct + wrong > 0) acc = (correct / (correct + wrong)) * 100;
    if (acc != null) {
      var accTxt = formatGaugePct(acc);
      var accArrow = acc >= 50 ? 'up' : 'down';
      setM('avg-acc', accTxt, accArrow);
      setM('win-rate', accTxt, accArrow);
      setMeter('avg-acc', acc);
      setMeter('win-rate', acc);
    } else {
      setM('avg-acc', '—');
      setM('win-rate', '—');
      setMeter('avg-acc', 0);
      setMeter('win-rate', 0);
    }
    var dw = stats.judge_weight_deltas || {};
    var signed = ['oracle', 'echo', 'pulse'].reduce(function (s, k) {
      return s + (typeof dw[k] === 'number' ? dw[k] : 0);
    }, 0);
    if (Math.abs(signed) >= 0.0005) {
      setM('signal', (signed >= 0 ? '+' : '') + signed.toFixed(2), signed >= 0 ? 'up' : 'down');
    } else {
      setM('signal', '·');
    }
    var active = (dailyPick && (dailyPick.pick || dailyPick.candidate)) || {};
    var tags = active.scenario_tags || {};
    var sn = active.subnet || {};
    var rsiN = sn.rsi != null ? Number(sn.rsi) : NaN;
    if (!isNaN(rsiN)) setM('rsi', String(Math.round(rsiN)), rsiN >= 50 ? 'up' : 'down');
    else if (tags.rsi) setM('rsi', String(tags.rsi).replace(/_/g, ' ').toUpperCase());
    var stochC = active.signal_contributions && active.signal_contributions.stochastic_reversal;
    var stochN = sn.stochastic_k != null ? Number(sn.stochastic_k) : NaN;
    if (isNaN(stochN) && stochC && stochC.score != null) {
      stochN = Number(stochC.score);
      if (stochN <= 1) stochN *= 100;
    }
    if (!isNaN(stochN)) setM('stoch', String(Math.round(stochN)), stochN >= 50 ? 'up' : 'down');
    var hv = dailyPick && dailyPick.horizon_views && dailyPick.horizon_views.views
      ? dailyPick.horizon_views.views['7d']
      : null;
    var d7 = sn.price_change_7d != null ? Number(sn.price_change_7d)
      : sn.change_7d != null ? Number(sn.change_7d)
      : active.price_change_7d != null ? Number(active.price_change_7d)
      : hv && hv.pct_7d != null ? Number(hv.pct_7d)
      : NaN;
    if (!isNaN(d7)) setM('d7', (d7 >= 0 ? '+' : '') + d7.toFixed(1) + '%', d7 >= 0 ? 'up' : 'down');
    var signals = judgeSignalsFromPick(dailyPick || {});
    var vals = ['oracle', 'echo', 'pulse'].map(function (k) { return signals[k]; }).filter(function (v) {
      return v != null && !isNaN(Number(v));
    }).map(Number);
    var varEl = hero.querySelector('.tribunal-hero__variance-value');
    var varFill = hero.querySelector('.tribunal-hero__variance-fill');
    if (vals.length >= 2) {
      var spread = Math.max.apply(null, vals) - Math.min.apply(null, vals);
      if (varEl) varEl.textContent = Math.round(spread) + ' pt';
      if (varFill) varFill.style.width = Math.max(0, Math.min(100, 100 - spread)) + '%';
    }
  }

  function patchTribunalRingFill(pct) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero) return;
    var clamped = 0;
    if (pct != null && !isNaN(Number(pct))) {
      clamped = Math.max(0, Math.min(100, Number(pct)));
    }
    var target = String(clamped);
    var inner = hero.querySelector('[data-conviction-arc]');
    if (inner) {
      inner.setAttribute('stroke-dasharray', clamped.toFixed(1) + ' ' + (100 - clamped).toFixed(1));
    }
    if (!hero.hasAttribute('data-ring-animated')) {
      hero.style.setProperty('--p', '0');
      hero.setAttribute('data-ring-animated', '1');
      // Animate 0 → real% on first paint
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          hero.style.setProperty('--p', target);
        });
      });
      return;
    }
    hero.style.setProperty('--p', target);
  }

  function formatSyncedAge(iso) {
    var ms = parseIsoMs(iso);
    if (!ms) return null;
    var age = Date.now() - ms;
    if (age < 60000) return 'just now';
    if (age < 3600000) return Math.floor(age / 60000) + 'm ago';
    var hours = Math.floor(age / 3600000);
    if (hours < 24) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
  }

  function patchTribunalSyncStamp(generatedAtIso) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero) return;
    var stamp = document.getElementById('tribunal-hero-sync');
    var iso = generatedAtIso;
    if (!iso) {
      var dossier = document.getElementById('k3-dossier');
      iso =
        hero.getAttribute('data-synced-at') ||
        (dossier ? dossier.getAttribute('data-generated-at') : null);
    }
    if (iso) hero.setAttribute('data-synced-at', iso);
    else hero.removeAttribute('data-synced-at');
    var age = formatSyncedAge(iso);
    if (!stamp) return;
    if (!age) {
      stamp.hidden = true;
      stamp.textContent = '';
      stamp.removeAttribute('data-synced-at');
      return;
    }
    stamp.setAttribute('data-synced-at', iso);
    stamp.textContent = 'Synced · ' + age;
    stamp.hidden = false;
  }

  function renderTribunalLast5Ticks(container, last5) {
    if (!container) return;
    if (!last5 || !last5.length) {
      container.hidden = true;
      return;
    }
    var ticks = container.querySelector('.tribunal-hero__last5-ticks');
    if (!ticks) return;
    ticks.innerHTML = last5.slice(0, 5).map(function (hit) {
      if (hit === true) return '<span class="tribunal-hero__tick tribunal-hero__tick--hit"></span>';
      if (hit === false) return '<span class="tribunal-hero__tick tribunal-hero__tick--miss"></span>';
      return '<span class="tribunal-hero__tick tribunal-hero__tick--empty"></span>';
    }).join('');
    container.hidden = false;
  }

  function patchTribunalCouncilLast5(stats) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero) return;
    var el = hero.querySelector('[data-council-last5]');
    if (!el) return;
    renderTribunalLast5Ticks(el, stats && stats.council_last5);
  }

  function patchTribunalJudges(stats, dailyPick) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero || !stats) return;
    var weights = stats.judge_weights || {};
    var signals = judgeSignalsFromPick(dailyPick || {});
    var last5Map = stats.judge_last5 || {};
    hero.querySelectorAll('[data-judge]').forEach(function (seat) {
      var key = seat.getAttribute('data-judge');
      var weightEl = seat.querySelector('[data-judge-weight]');
      if (weightEl) weightEl.textContent = formatJudgeWeightPct(weights[key], weights);
      var signalEl = seat.querySelector('[data-judge-signal]');
      if (signalEl) signalEl.textContent = formatGaugePct(signals[key]);
      var last5El = seat.querySelector('[data-last5]');
      if (last5El) renderTribunalLast5Ticks(last5El, last5Map[key]);
    });
  }

  function setTribunalPanelField(el, next) {
    if (!el || next == null) return;
    var cur = (el.textContent || '').trim();
    if (next === '—' && cur && cur !== '—') return;
    el.textContent = next;
  }

  function patchTribunalPanels(dailyPick, stats) {
    var hero = document.getElementById('tribunal-hero');
    if (!hero || !stats) return;
    var kind = verdictKind(dailyPick || {});
    var gauge = tribunalGaugePct(dailyPick, stats);
    var active = (dailyPick && (dailyPick.pick || dailyPick.candidate)) || {};
    var tb = stats.trust_banner || {};
    var deltas = stats.judge_weight_deltas || {};

    var vEl = hero.querySelector('[data-decision-verdict]');
    if (vEl) vEl.textContent = kind.toUpperCase();
    var cEl = hero.querySelector('[data-decision-confidence]');
    if (cEl) cEl.textContent = formatGaugePct(gauge);
    var consEl = hero.querySelector('[data-decision-consensus]');
    if (consEl) {
      var agreement = judgeAgreementLabels(judgeSignalsFromPick(dailyPick || {}));
      if (agreement.consensus !== '—') {
        setTribunalPanelField(consEl, agreement.consensus);
      } else {
        var cs = active.consensus_score;
        if (cs != null && !isNaN(Number(cs))) {
          var cn = Number(cs);
          setTribunalPanelField(
            consEl,
            (cn <= 1 ? Math.round(cn * 100) : Math.round(cn)) + '%'
          );
        } else setTribunalPanelField(consEl, '—');
      }
    }
    var brainEl = hero.querySelector('[data-decision-brain]');
    if (brainEl) {
      var brain = active.brain_recommendation || active.recommended_action || dailyPick.brain_recommendation;
      if (brain && typeof brain === 'object') brain = brain.action || brain.recommended_action;
      brainEl.textContent = brain ? String(brain).toUpperCase() : '—';
    }
    var dissentEl = hero.querySelector('[data-decision-dissent]');
    if (dissentEl) {
      var spreadAgreement = judgeAgreementLabels(judgeSignalsFromPick(dailyPick || {}));
      if (spreadAgreement.dissent !== '—') {
        setTribunalPanelField(dissentEl, spreadAgreement.dissent);
      } else {
        var dissenters = dailyPick.dissenters || active.dissenters;
        if (dissenters && dissenters.length) setTribunalPanelField(dissentEl, dissenters.join(', '));
        else if (dailyPick.council_unanimous) setTribunalPanelField(dissentEl, 'Unanimous');
        else setTribunalPanelField(dissentEl, '—');
      }
    }

    var graded = Number(tb.graded) || 0;
    var correct = Number(tb.correct) || 0;
    var wrong = Number(tb.wrong) || 0;
    var winRate = '—';
    if (tb.ready && tb.accuracy != null) winRate = (Math.round(Number(tb.accuracy) * 1000) / 10).toFixed(1) + '%';
    else if (graded > 0 && correct + wrong > 0) {
      winRate = (Math.round((correct / (correct + wrong)) * 1000) / 10).toFixed(1) + '%';
    }
    var wrEl = hero.querySelector('[data-accuracy-win-rate]');
    if (wrEl) wrEl.textContent = winRate;
    var subEl = hero.querySelector('[data-accuracy-sub]');
    if (subEl) subEl.textContent = tb.headline || tb.message || 'Building sample';
    var gEl = hero.querySelector('[data-accuracy-graded]');
    if (gEl) gEl.textContent = String(graded);
    var hitEl = hero.querySelector('[data-accuracy-correct]');
    if (hitEl) hitEl.textContent = String(correct);
    var missEl = hero.querySelector('[data-accuracy-wrong]');
    if (missEl) missEl.textContent = String(wrong);

    patchTribunalCouncilLast5(stats);

    hero.querySelectorAll('[data-jury]').forEach(function (row) {
      var key = row.getAttribute('data-jury');
      var delta = deltas[key];
      var arrowEl = row.querySelector('[data-jury-arrow]');
      var deltaEl = row.querySelector('[data-jury-delta]');
      if (delta == null || isNaN(Number(delta))) {
        if (arrowEl) {
          arrowEl.textContent = '·';
          arrowEl.setAttribute('data-arrow', '·');
        }
        if (deltaEl) deltaEl.textContent = '—';
        return;
      }
      var d = Number(delta);
      if (arrowEl) {
        var arrowGlyph = d > 0.0005 ? '▲' : d < -0.0005 ? '▼' : '·';
        arrowEl.textContent = arrowGlyph;
        arrowEl.setAttribute('data-arrow', arrowGlyph);
      }
      if (deltaEl) deltaEl.textContent = (d >= 0 ? '+' : '') + d.toFixed(3);
    });
  }

  function renderTribunalHero(dailyPick, learningStats) {
    var hero = document.getElementById('tribunal-hero');
    // #region agent log
    debugHydration('D', 'tribunal hero render entered', {
      hero: !!hero,
      payload: !!dailyPick,
      stats: !!learningStats,
      status: dailyPick && dailyPick.status || null,
    });
    // #endregion
    if (!hero || !dailyPick) return false;
    var kind = verdictKind(dailyPick);
    hero.setAttribute('data-verdict-kind', kind);
    var pct = kind === 'forming' || kind === 'cold' ? null : tribunalGaugePct(dailyPick, learningStats);
    var temp = convictionTemp(kind, pct);
    hero.setAttribute('data-temp', temp);
    syncCouncilTemp(temp);
    var title = document.getElementById('tribunal-hero-title');
    if (title) title.textContent = tribunalSubnetLabel(dailyPick);
    var badge = document.getElementById('k3-action-badge');
    var pills = tribunalVerdictPills(dailyPick, kind);
    if (badge) badge.textContent = pills.gate;
    var holdBadge = document.getElementById('k3-action-hold');
    if (holdBadge) {
      if (pills.action) {
        holdBadge.textContent = pills.action;
        holdBadge.hidden = false;
      } else {
        holdBadge.textContent = '';
        holdBadge.hidden = true;
      }
    }
    var orb = document.getElementById('k3-orb-score');
    if (orb) orb.textContent = formatGaugePct(pct);
    patchTribunalRingFill(pct);
    if (pct != null) {
      hero.setAttribute('data-hero-conviction', String(pct));
      var dossier = document.getElementById('k3-dossier');
      if (dossier) dossier.setAttribute('data-hero-conviction', String(pct));
    } else {
      hero.removeAttribute('data-hero-conviction');
    }
    patchTribunalSyncStamp(dailyPickGeneratedAt(dailyPick));
    var headline = document.getElementById('k3-call-headline');
    if (headline) {
      var line = tribunalCenterLabel(dailyPick, kind);
      if (pct != null) line += ' — ' + formatGaugePct(pct) + ' conviction';
      headline.textContent = line;
    }
    if (learningStats) {
      patchTribunalJudges(learningStats, dailyPick);
      patchTribunalPanels(dailyPick, learningStats);
      patchTribunalInstrument(learningStats, dailyPick);
      patchTribunalEyeArcs(learningStats.judge_weights);
    }
    // #region agent log
    debugHydration('D', 'tribunal hero render completed', {
      kind: kind,
      temp: temp,
      conviction: pct,
      title: title && title.textContent || null,
      actionBadge: badge && badge.textContent || null,
    });
    // #endregion
    return true;
  }

  // Canonical K3 dossier writer: renderDailyPick → patchK3DossierFromPayload.
  // home_live_refresh.js delegates here when #k3-dossier exists — no third writer.
  window.__cockpitHome = {
    renderHero: renderHero,
    renderDailyPick: renderDailyPick,
    renderPumpAlerts: renderPumpAlerts,
    renderTribunalHero: renderTribunalHero,
    verdictKind: verdictKind,
  };

  if (document.getElementById('tribunal-hero')) {
    patchTribunalSyncStamp();
  }
})();
