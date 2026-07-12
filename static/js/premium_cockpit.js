/* Phase H-full — premium cockpit client hydration (vanilla JS + Chart.js) */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function fmtNum(n, d) {
    if (n == null || isNaN(n)) return '—';
    var x = Number(n);
    if (x >= 1e9) return (x / 1e9).toFixed(d || 2) + 'B';
    if (x >= 1e6) return (x / 1e6).toFixed(d || 2) + 'M';
    if (x >= 1e3) return (x / 1e3).toFixed(d || 2) + 'K';
    return x.toLocaleString(undefined, { maximumFractionDigits: d || 2 });
  }
  function fetchJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    });
  }

  var ctx = {};
  try {
    var el = $('premium-ctx');
    if (el) ctx = JSON.parse(el.textContent || '{}');
  } catch (e) {
    console.error('premium-ctx parse failed', e);
  }

  var subnets = Array.isArray(ctx.subnets) ? ctx.subnets : [];

  /* ---------- Undervalued scoring (client mirror of server_original) ---------- */
  function computeUndervalued(list) {
    var ranked = (list || []).map(function (sn) {
      var emission = Number(sn.emission || 0);
      var apy = Number(sn.apy || sn.staking_data && sn.staking_data.apy || 0);
      var chg = Number(sn.price_change_24h || 0);
      var mc = Number(sn.market_cap || 0);
      var vol = Number(sn.volume || 0);
      var score = 0;
      if (emission > 0) score += emission * 10;
      if (apy > 0) score += apy * 0.6;
      if (chg > -5) score += Math.max(chg, -5);
      if (vol > 0) score += Math.log(vol + 1);
      if (mc > 0) score -= Math.log(mc + 1) * 0.3;
      score = Math.max(0, Math.min(100, score));
      return Object.assign({}, sn, {
        undervalued_score: Math.round(score * 100) / 100,
        significantly_undervalued: score > 85
      });
    });
    ranked.sort(function (a, b) { return (b.undervalued_score || 0) - (a.undervalued_score || 0); });
    return ranked.slice(0, 8).map(function (sn, i) {
      sn.rank = i + 1;
      return sn;
    });
  }

  function renderUndervalued() {
    var grid = $('undervalued-grid');
    var empty = $('undervalued-empty');
    if (!grid) return;
    var rows = computeUndervalued(subnets);
    if (!rows.length) {
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    grid.innerHTML = '<table class="tbl"><thead><tr><th>#</th><th>Subnet</th><th>APY</th><th>24h</th><th>Score</th><th>Flag</th></tr></thead><tbody>' +
      rows.map(function (sn) {
        var apy = Number(sn.apy || (sn.staking_data && sn.staking_data.apy) || 0);
        var chg = Number(sn.price_change_24h || 0);
        return '<tr><td>' + sn.rank + '</td><td class="text-primary">' + esc(sn.name || 'SN' + sn.netuid) +
          ' <span class="pick-meta">SN' + esc(sn.netuid || sn.id) + '</span></td><td>' + apy.toFixed(1) + '%</td><td>' +
          (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%</td><td><b>' + sn.undervalued_score.toFixed(1) + '</b></td><td>' +
          (sn.significantly_undervalued ? '<span class="badge badge-buy">DEEP VALUE</span>' : '—') + '</td></tr>';
      }).join('') + '</tbody></table>';
    return rows;
  }

  /* ---------- Technical indicators ---------- */
  function syntheticSpark(sn) {
    var p = Number(sn.price || 1);
    var c24 = Number(sn.price_change_24h || 0) / 100;
    var c7 = Number(sn.price_change_7d || 0) / 100;
    var pts = [];
    for (var i = 0; i < 12; i++) {
      var t = i / 11;
      pts.push(p * (1 + c7 * t * 0.3 + c24 * t * 0.7));
    }
    return pts;
  }

  function renderTechnicalIndicators() {
    var heat = $('ti-heat-row');
    var grid = $('ti-spark-grid');
    var meta = $('ti-meta');
    var empty = $('ti-empty');
    var conv = (ctx.api_indicators_convergence && ctx.api_indicators_convergence.subnets) || [];
    if (!conv.length) {
      if (empty) empty.style.display = '';
      if (meta) meta.textContent = 'no convergence data';
      return;
    }
    if (empty) empty.style.display = 'none';
    if (meta) meta.textContent = conv.length + ' subnets tracked';
    if (heat) {
      heat.innerHTML = conv.map(function (row) {
        var os = row.oversold || {};
        var ob = row.overbought || {};
        var active = os.convergent ? os : (ob.convergent ? ob : null);
        var pct = active ? Math.round((active.agreement || active.count / (active.total || 1)) * 100) : 10;
        var label = active ? (active.type || 'neutral').toUpperCase() : '—';
        return '<div class="mini-timeline-seg" style="flex:' + Math.max(pct, 8) + '" title="' + esc(row.name) + ' ' + label + '">' +
          '<span class="mini-timeline-label">' + esc((row.name || '').split(' ')[0]) + '</span></div>';
      }).join('');
    }
    if (grid) {
      grid.innerHTML = conv.map(function (row) {
        var sn = subnets.find(function (s) { return s.netuid === row.netuid || s.id === row.netuid; }) || {};
        var pts = syntheticSpark(sn);
        return '<div class="ind-cell card"><div class="ti-head"><div class="pick-name">' + esc(row.name || 'SN' + row.netuid) +
          '</div><span class="pick-meta">SN' + esc(row.netuid) + '</span></div>' +
          '<div class="spark-wrap"><canvas class="spark" width="120" height="36" data-spark="' + pts.join(',') + '"></canvas></div></div>';
      }).join('');
      if (window.Chart) {
        grid.querySelectorAll('canvas.spark').forEach(function (canvas) {
          if (typeof drawSpark === 'function') return;
          var raw = canvas.getAttribute('data-spark');
          if (!raw) return;
          var pts = raw.split(',').map(Number).filter(function (n) { return !isNaN(n); });
          if (pts.length < 2) return;
          var up = pts[pts.length - 1] >= pts[0];
          var col = up ? '#00ff41' : '#ff4d5e';
          new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: { labels: pts.map(function (_, i) { return i; }), datasets: [{ data: pts, borderColor: col, fill: false, tension: 0.4, pointRadius: 0, borderWidth: 1.5 }] },
            options: { responsive: false, animation: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } } }
          });
        });
      }
    }
  }

  /* ---------- Staking grid ---------- */
  function renderStaking() {
    var grid = $('staking-grid');
    var empty = $('staking-empty');
    if (!grid) return;
    var ranked = subnets.slice().sort(function (a, b) {
      var ay = Number(a.apy || (a.staking_data && a.staking_data.apy) || 0);
      var by = Number(b.apy || (b.staking_data && b.staking_data.apy) || 0);
      return by - ay;
    }).filter(function (s) {
      return Number(s.apy || (s.staking_data && s.staking_data.apy) || 0) > 0;
    }).slice(0, 8);
    if (!ranked.length) {
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    grid.innerHTML = ranked.map(function (sn) {
      var apy = Number(sn.apy || (sn.staking_data && sn.staking_data.apy) || 0);
      var stake = Number(sn.total_stake || (sn.staking_data && sn.staking_data.total_stake) || sn.stake || 0);
      return '<div class="metric card"><div class="lbl">' + esc(sn.name || 'SN' + sn.netuid) + '</div>' +
        '<div class="val pos">' + apy.toFixed(2) + '%</div><div class="sub">stake ' + fmtNum(stake, 0) + ' TAO</div></div>';
    }).join('');
  }

  /* ---------- Social ---------- */
  function renderSocial() {
    var grid = $('social-grid');
    var empty = $('social-empty');
    if (!grid) return;
    var withMentions = subnets.filter(function (s) { return Number(s.social_mentions || 0) > 0; })
      .sort(function (a, b) { return Number(b.social_mentions) - Number(a.social_mentions); }).slice(0, 8);
    if (!withMentions.length) {
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    grid.innerHTML = withMentions.map(function (sn) {
      var m = Number(sn.social_mentions || 0);
      var label = m > 50 ? 'bullish' : (m > 10 ? 'neutral' : 'bearish');
      return '<div class="metric card"><div class="lbl">' + esc(sn.name || 'SN' + sn.netuid) + '</div>' +
        '<div class="val">' + m + '</div><div class="sub"><span class="badge badge-' +
        (label === 'bullish' ? 'buy' : label === 'bearish' ? 'sell' : 'hold') + '">' + label + '</span></div></div>';
    }).join('');
  }

  /* ---------- Council dispositions ---------- */
  function renderCouncilDispositions() {
    var grid = $('council-dispositions');
    var empty = $('council-disp-empty');
    var meta = $('council-disp-meta');
    if (!grid) return;
    fetchJSON('/api/daily-rotation').then(function (payload) {
      var decisions = (((payload || {}).data || {}).decisions) || [];
      if (!decisions.length) {
        if (empty) empty.style.display = '';
        if (meta) meta.textContent = '0 dispositions';
        return;
      }
      if (empty) empty.style.display = 'none';
      if (meta) meta.textContent = decisions.length + ' dispositions';
      grid.innerHTML = decisions.slice(0, 9).map(function (d) {
        var action = (d.recommended_action || d.action || 'hold').toString().toLowerCase();
        var badge = action === 'accumulate' || action === 'buy' ? 'badge-buy' :
          action === 'reduce' || action === 'sell' ? 'badge-sell' : 'badge-hold';
        return '<div class="expert card-soft"><div class="avatar">' + esc(String(d.subnet_id || '?')) + '</div>' +
          '<div class="name">' + esc(d.subnet_name || d.name || 'Subnet ' + d.subnet_id) + '</div>' +
          '<span class="badge ' + badge + '">' + esc(action) + '</span></div>';
      }).join('');
    }).catch(function () {
      if (empty) empty.style.display = '';
      if (meta) meta.textContent = 'unavailable';
    });
  }

  /* ---------- Judges ---------- */
  function renderJudges() {
    var grid = $('judges-grid');
    var empty = $('judges-empty');
    if (!grid) return;
    fetchJSON('/api/judges').then(function (data) {
      var judges = (data && data.judges) || [];
      if (!judges.length) {
        if (empty) { empty.textContent = 'No judge data available.'; empty.style.display = ''; }
        return;
      }
      if (empty) empty.style.display = 'none';
      grid.innerHTML = judges.slice(0, 9).map(function (j) {
        var verdict = (j.consensus && j.consensus.verdict) || 'neutral';
        var vc = verdict === 'bullish' ? 'badge-buy' : verdict === 'bearish' ? 'badge-sell' : 'badge-hold';
        var score = j.consensus ? j.consensus.score.toFixed(2) : '—';
        return '<div class="card pick"><div class="pick-name">' + esc(j.name || 'SN' + j.netuid) + '</div>' +
          '<div class="pick-meta">SN' + esc(j.netuid) + ' · Oracle ' + (j.oracle ? j.oracle.score.toFixed(2) : '—') + '</div>' +
          '<div class="tags" style="margin-top:8px;"><span class="badge ' + vc + '">' + esc(verdict) + '</span>' +
          '<span class="badge badge-watch">score ' + score + '</span></div></div>';
      }).join('');
    }).catch(function (e) {
      if (empty) { empty.textContent = 'Judge API unavailable: ' + e.message; empty.style.display = ''; }
    });
  }

  /* ---------- Radar chart ---------- */
  function renderRadar(undervalued) {
    var canvas = $('radarChart');
    var overlay = $('radar-overlay-list');
    var empty = $('radar-empty');
    if (!canvas || !window.Chart) return;
    var top = (undervalued || computeUndervalued(subnets)).slice(0, 3);
    if (top.length < 2) {
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    var labels = ['Emission', 'APY', '24h', 'Volume', 'Score'];
    var datasets = top.map(function (sn, i) {
      var colors = ['#00ff41', '#22d3ee', '#8b5cf6'];
      var norm = function (v, max) { return max ? Math.min(100, (v / max) * 100) : 0; };
      var maxE = Math.max.apply(null, top.map(function (s) { return Number(s.emission || 0); })) || 1;
      var maxV = Math.max.apply(null, top.map(function (s) { return Number(s.volume || 0); })) || 1;
      return {
        label: sn.name || 'SN' + sn.netuid,
        color: colors[i % colors.length],
        data: [
          norm(Number(sn.emission || 0), maxE),
          Math.min(100, Number(sn.apy || 0) * 10),
          Math.min(100, Math.max(0, 50 + Number(sn.price_change_24h || 0))),
          norm(Number(sn.volume || 0), maxV),
          Number(sn.undervalued_score || 0)
        ]
      };
    });
    canvas.setAttribute('data-radar', JSON.stringify({ labels: labels, datasets: datasets }));
    if (overlay) {
      overlay.innerHTML = top.map(function (sn) {
        return '<div class="radar-item"><div class="name">' + esc(sn.name) + '</div><div class="meta">score ' +
          sn.undervalued_score.toFixed(1) + ' · ' + (sn.significantly_undervalued ? 'DEEP VALUE' : 'watch') + '</div></div>';
      }).join('');
    }
    /* Trigger app.js radar init if loaded; else inline */
    try {
      var radarData = JSON.parse(canvas.getAttribute('data-radar'));
      new Chart(canvas.getContext('2d'), {
        type: 'radar',
        data: {
          labels: radarData.labels,
          datasets: radarData.datasets.map(function (ds) {
            return {
              label: ds.label,
              data: ds.data,
              borderColor: ds.color,
              backgroundColor: ds.color.replace(')', ',0.15)').replace('rgb', 'rgba').replace('#', ''),
              borderWidth: 2,
              pointRadius: 2
            };
          })
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: '#8cb39f' } } },
          scales: {
            r: {
              angleLines: { color: 'rgba(233,247,239,0.06)' },
              grid: { color: 'rgba(233,247,239,0.06)' },
              pointLabels: { color: '#8cb39f' },
              ticks: { display: false },
              suggestedMin: 0,
              suggestedMax: 100
            }
          }
        }
      });
    } catch (e) { console.error('radar', e); }
  }

  /* ---------- Trace API supplement ---------- */
  function renderTraceApi() {
    var host = $('trace-api-rows');
    if (!host) return;
    fetchJSON('/api/trace/list').then(function (payload) {
      var rows = (payload && payload.traces) || (payload && payload.data) || [];
      if (!Array.isArray(rows) || !rows.length) return;
      host.innerHTML = '<p class="section-sub" style="margin-top:12px;">API trace (' + rows.length + ')</p><table class="tbl"><thead><tr><th>ID</th><th>Outcome</th><th>Resolved</th></tr></thead><tbody>' +
        rows.slice(0, 6).map(function (r) {
          return '<tr><td>' + esc(r.trace_id || r.id || '—') + '</td><td>' + esc(r.outcome || '—') + '</td><td>' + esc(r.resolved_at || '—') + '</td></tr>';
        }).join('') + '</tbody></table>';
    }).catch(function () { /* honest-empty */ });
  }

  /* ---------- Scanner (registry table) ---------- */
  function initScanner() {
    var stage = $('scanner-stage');
    var meta = $('scanner-meta');
    var search = $('scanner-search');
    var sort = $('scanner-sort');
    if (!stage) return;

    var state = { filter: 'all', q: '', sort: 'id', registry: [] };

    function getField(item, field) {
      if (field === 'apy') return item.staking_data && item.staking_data.apy || item.apy;
      if (field === 'consensus_score') return item.consensus && item.consensus.score;
      return item[field];
    }

    function filtered() {
      var items = state.registry.slice();
      if (state.filter !== 'all') {
        items = items.filter(function (i) { return (i.status || '').toLowerCase() === state.filter; });
      }
      if (state.q) {
        var q = state.q.toLowerCase();
        items = items.filter(function (i) {
          return String(i.id || i.netuid || '').includes(q) ||
            (i.name || '').toLowerCase().includes(q) ||
            (i.status || '').toLowerCase().includes(q);
        });
      }
      items.sort(function (a, b) {
        var av = getField(a, state.sort) || 0;
        var bv = getField(b, state.sort) || 0;
        if (typeof av === 'string') return String(av).localeCompare(String(bv));
        return av - bv;
      });
      return items;
    }

    function render() {
      var items = filtered();
      if (meta) meta.textContent = items.length + ' subnets';
      if (!items.length) {
        stage.innerHTML = '<p class="empty">No subnets match filters.</p>';
        return;
      }
      stage.innerHTML = '<table class="tbl"><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Emission</th><th>APY</th><th>Consensus</th></tr></thead><tbody>' +
        items.slice(0, 50).map(function (item) {
          var id = item.id != null ? item.id : item.netuid;
          var apy = getField(item, 'apy');
          var score = getField(item, 'consensus_score');
          return '<tr><td>#' + esc(id) + '</td><td>' + esc(item.name || 'Unnamed') + '</td><td>' + esc(item.status || '—') + '</td><td>' +
            fmtNum(item.emission, 3) + '</td><td>' + (apy != null ? (Number(apy) * (apy < 2 ? 100 : 1)).toFixed(2) + '%' : '—') + '</td><td>' +
            (score != null ? (Number(score) * 100).toFixed(0) + '%' : '—') + '</td></tr>';
        }).join('') + '</tbody></table>';
    }

    fetchJSON('/api/registry').then(function (data) {
      state.registry = Object.keys(data).map(function (k) {
        var v = Object.assign({}, data[k]);
        v.id = v.id != null ? v.id : Number(k);
        return v;
      });
      render();
    }).catch(function () {
      state.registry = subnets.map(function (s) {
        var v = Object.assign({}, s);
        v.id = v.id != null ? v.id : v.netuid;
        return v;
      });
      render();
    });

    document.querySelectorAll('#scanner-filters .tab-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('#scanner-filters .tab-btn').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.filter = btn.getAttribute('data-filter');
        render();
      });
    });
    if (search) search.addEventListener('input', function () { state.q = search.value.trim(); render(); });
    if (sort) sort.addEventListener('change', function () { state.sort = sort.value; render(); });
  }

  /* ---------- Boot ---------- */
  function boot() {
    var uv = renderUndervalued();
    renderTechnicalIndicators();
    renderStaking();
    renderSocial();
    renderCouncilDispositions();
    renderJudges();
    renderRadar(uv);
    renderTraceApi();
    initScanner();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
