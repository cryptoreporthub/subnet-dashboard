(function () {
  'use strict';

  // Vivid, brand-aligned identity per node kind — the "call" (disposition) is the
  // hottest color since it's literally the outcome the trail builds toward.
  const KIND_COLORS = {
    subnet: '#3fc9ff',
    signal: '#a78bfa',
    judge: '#ffb74a',
    prediction: '#34d399',
    scenario: '#b8a8f0',
    disposition: '#ff5fa8',
    indicator: '#2dd4bf',
    whale: '#38bdf8',
    risk: '#f87171',
    loop: '#f8fafc',
  };

  // Narrative order: evidence seen -> market context -> judges weigh it -> forecast -> outcome.
  const KIND_ORDER = {
    signal: 0,
    indicator: 0,
    scenario: 1,
    whale: 1,
    risk: 1,
    judge: 2,
    prediction: 3,
    disposition: 4,
  };

  function kindColor(kind) {
    return KIND_COLORS[kind] || '#9CA3AF';
  }

  // Mirror of the Jinja `sn_band` formula and k3NetuidBand() in council_stage.html —
  // keeps a subnet's Trail card the same hue as its Hero orb.
  function netuidBand(netuid) {
    const n = parseInt(netuid, 10);
    if (isNaN(n) || n < 0) return 0;
    return ((n * 47) + 11) % 6;
  }

  function humanDetailLine(node) {
    const kind = (node && node.kind) || '';
    const metrics = (node && node.metrics) || {};
    if (kind === 'disposition') {
      return `Disposition · ${metrics.action || 'n/a'}${metrics.score != null ? ' · score ' + metrics.score : ''}`;
    }
    if (kind === 'prediction') {
      return `Prediction · ${metrics.decision || node.label || 'tracked'}`;
    }
    if (kind === 'signal') {
      return `Signal · ${node.label || kind}`;
    }
    if (kind === 'judge') {
      return `Judge · ${node.label || kind}`;
    }
    if (kind === 'scenario') {
      return `Scenario · ${node.label || kind}`;
    }
    if (kind === 'indicator') {
      return `Indicator · ${node.label || kind}`;
    }
    if (kind === 'whale') {
      return `Whale · ${node.label || 'smart money entry'}`;
    }
    if (kind === 'risk') {
      return `Risk · ${node.label || 'rugger exit warning'}`;
    }
    if (kind === 'subnet' || kind === 'loop') {
      const n = metrics.event_count != null ? `${metrics.event_count} trail events` : 'subnet node';
      return `${node.label || node.id} · ${n}`;
    }
    return node.label || node.id || '';
  }

  function rowMetaLine(node) {
    const m = (node && node.metrics) || {};
    const parts = [];
    if (m.action != null && m.action !== '') parts.push(String(m.action));
    if (m.score != null && m.score !== '') parts.push('score ' + m.score);
    if (m.decision != null && m.decision !== '') parts.push(String(m.decision));
    if (m.urgency != null && m.urgency !== '') parts.push(String(m.urgency) + ' urgency');
    if (m.estimated_exit_in_hours != null) parts.push('exit in ~' + m.estimated_exit_in_hours + 'h');
    if (m.win_rate != null) parts.push(Math.round(m.win_rate * 100) + '% win rate');
    if (m.avg_return_pct != null) parts.push(m.avg_return_pct + '% avg return');
    return parts.join(' · ');
  }

  function setEmptyMessage(root, message, show) {
    const empty = root.querySelector('#mindmap-graph-empty');
    const list = root.querySelector('#mindmap-trail-list');
    if (empty) {
      if (message) empty.textContent = message;
      empty.classList.toggle('hidden', !show);
    }
    if (list) list.classList.toggle('hidden', show);
  }

  // The graph is a star per hub: every other node is reached by exactly one
  // edge whose source is a hub. Hubs are usually a subnet, but judge/weight
  // nudge events with no netuid attach to the single "loop:council" hub
  // instead of a subnet — the loop tuning itself, not any one subnet's
  // evidence chain. So "group by subnet" generalizes to "group by hub."
  function buildTrailGroups(nodes, edges) {
    const nodeById = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const subnets = nodes.filter((n) => n.kind === 'subnet' || n.kind === 'loop');
    const rowsBySubnet = {};
    edges.forEach((edge) => {
      const target = nodeById[edge.target];
      if (!target) return;
      if (!rowsBySubnet[edge.source]) rowsBySubnet[edge.source] = [];
      rowsBySubnet[edge.source].push(target);
    });

    let freshestId = null;
    let freshestAt = '';
    nodes.forEach((n) => {
      const at = n.updated_at || '';
      if (at > freshestAt) {
        freshestAt = at;
        freshestId = n.id;
      }
    });

    const groups = subnets.map((subnet) => {
      const isLoop = subnet.kind === 'loop';
      const rows = (rowsBySubnet[subnet.id] || []).slice().sort((a, b) => {
        const oa = KIND_ORDER[a.kind] != null ? KIND_ORDER[a.kind] : 9;
        const ob = KIND_ORDER[b.kind] != null ? KIND_ORDER[b.kind] : 9;
        return oa - ob;
      });
      const netuid = isLoop ? null : String(subnet.id).split(':')[1];
      return { subnet, rows, netuid, freshestId, isLoop };
    });

    // The loop's own self-adjustment leads — it's the brain tuning itself,
    // not tied to any one subnet's recency.
    groups.sort((a, b) => {
      if (a.isLoop !== b.isLoop) return a.isLoop ? -1 : 1;
      return (b.subnet.updated_at || '').localeCompare(a.subnet.updated_at || '');
    });
    return groups;
  }

  function renderRow(row, freshestId) {
    const li = document.createElement('li');
    li.className = 'mindmap-trail-row' + (row.id === freshestId ? ' mindmap-trail-row--fresh' : '');
    const dot = document.createElement('span');
    dot.className = 'mindmap-trail-row__dot';
    dot.style.background = kindColor(row.kind);
    dot.style.color = kindColor(row.kind);
    const body = document.createElement('div');
    body.className = 'mindmap-trail-row__body';
    const kindEl = document.createElement('p');
    kindEl.className = 'mindmap-trail-row__kind';
    kindEl.textContent = row.kind || '';
    const line = document.createElement('p');
    line.className = 'mindmap-trail-row__line';
    line.textContent = humanDetailLine(row);
    body.appendChild(kindEl);
    body.appendChild(line);
    const meta = rowMetaLine(row);
    if (meta) {
      const metaEl = document.createElement('p');
      metaEl.className = 'mindmap-trail-row__meta';
      metaEl.textContent = meta;
      body.appendChild(metaEl);
    }
    li.appendChild(dot);
    li.appendChild(body);
    return li;
  }

  function renderGroup(group, index) {
    const details = document.createElement('details');
    details.className = 'mindmap-trail-group';
    details.dataset.subnetId = group.subnet.id;
    if (group.isLoop) {
      details.setAttribute('data-loop', '1');
    } else {
      details.setAttribute('data-band', String(netuidBand(group.netuid)));
    }
    if (index < 3) details.open = true;

    const summary = document.createElement('summary');
    summary.className = 'mindmap-trail-group__summary';
    const dot = document.createElement('span');
    dot.className = 'mindmap-trail-group__dot';
    const name = document.createElement('span');
    name.className = 'mindmap-trail-group__name';
    name.textContent = group.subnet.label || group.subnet.id;
    const count = document.createElement('span');
    count.className = 'mindmap-trail-group__count';
    count.textContent = group.rows.length + (group.rows.length === 1 ? ' event' : ' events');
    const chevron = document.createElement('span');
    chevron.className = 'mindmap-trail-group__chevron';
    chevron.textContent = '\u203a';
    summary.appendChild(dot);
    summary.appendChild(name);
    summary.appendChild(count);
    summary.appendChild(chevron);
    details.appendChild(summary);

    const rowsList = document.createElement('ul');
    rowsList.className = 'mindmap-trail-rows';
    group.rows.forEach((row) => rowsList.appendChild(renderRow(row, group.freshestId)));
    details.appendChild(rowsList);

    return details;
  }

  function renderTrail(root, graph) {
    const list = root.querySelector('#mindmap-trail-list');
    if (!list) return;

    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const edges = Array.isArray(graph.edges) ? graph.edges : [];

    list.innerHTML = '';
    if (!nodes.length) {
      setEmptyMessage(
        root,
        'Mindmap graph is empty — no trail, disposition, or scenario nodes yet. Data will appear as the learning loop records events.',
        true
      );
      return;
    }

    setEmptyMessage(root, '', false);
    const groups = buildTrailGroups(nodes, edges);
    groups.forEach((group, index) => list.appendChild(renderGroup(group, index)));
    root.dataset.rendered = '1';
  }

  async function fetchGraph(root) {
    const initial = root.dataset.initialGraph;
    if (initial) {
      try {
        return JSON.parse(initial);
      } catch (_) {
        /* fall through to fetch */
      }
    }

    const base = root.dataset.api || '/api/mindmap/graph';
    const focus =
      window.LivingFocus && window.LivingFocus.netuid != null
        ? window.LivingFocus.netuid
        : null;
    const api = focus != null ? base + '?focus=' + encodeURIComponent(focus) : base;
    try {
      const signal =
        typeof AbortSignal !== 'undefined' && AbortSignal.timeout
          ? AbortSignal.timeout(6000)
          : undefined;
      const resp = await fetch(api, {
        headers: { Accept: 'application/json' },
        signal: signal,
      });
      if (!resp.ok) {
        return { status: 'unavailable', nodes: [], edges: [] };
      }
      return await resp.json();
    } catch (_) {
      return { status: 'unavailable', nodes: [], edges: [] };
    }
  }

  async function refreshGraph() {
    const root = document.getElementById('mindmap-graph-root');
    if (!root) return;
    const graph = await fetchGraph(root);
    if (graph.status === 'unavailable') {
      setEmptyMessage(
        root,
        'Mindmap graph API is unavailable on this deploy. The panel will activate when /api/mindmap/graph is wired.',
        true
      );
      return;
    }
    if (graph.status === 'degraded' && !(graph.nodes || []).length) {
      setEmptyMessage(
        root,
        graph.detail ||
          'Worker volume temporarily unavailable — trail will refill when the learning loop reconnects.',
        true
      );
      return;
    }
    if (graph.scoped && !(graph.nodes || []).length) {
      setEmptyMessage(root, 'No graph edges for this focus subnet yet — trail fills as picks resolve.', true);
    } else {
      renderTrail(root, graph);
    }
  }

  async function init() {
    const root = document.getElementById('mindmap-graph-root');
    if (!root) return;
    await refreshGraph();
    document.addEventListener('living-focus:change', refreshGraph);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
