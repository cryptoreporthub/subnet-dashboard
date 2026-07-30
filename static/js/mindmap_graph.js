(function () {
  'use strict';

  // Vivid, brand-aligned identity per node kind — the "call" (disposition) is the
  // hottest color since it's literally the outcome the whole graph builds toward.
  const KIND_COLORS = {
    subnet: '#3fc9ff',
    signal: '#a78bfa',
    judge: '#ffb74a',
    prediction: '#34d399',
    scenario: '#b8a8f0',
    disposition: '#ff5fa8',
  };

  // Concentric "brain" layout — signals/evidence sit on the outer rim, judges
  // deliberate in the middle, and the call (disposition/prediction) lands closest
  // to the pulsing core. Every real edge already points source(subnet, outer) ->
  // target(inner kind), so this reads as evidence flowing inward toward a decision.
  const RING_RADIUS = {
    subnet: 1.0,
    scenario: 0.88,
    signal: 0.76,
    prediction: 0.6,
    judge: 0.42,
    disposition: 0.24,
  };

  function kindColor(kind) {
    return KIND_COLORS[kind] || '#9CA3AF';
  }

  function ringRadiusFraction(kind) {
    return RING_RADIUS[kind] != null ? RING_RADIUS[kind] : 0.7;
  }

  function layoutNodes(nodes, width, height) {
    const count = nodes.length;
    if (!count) return {};
    const cx = width / 2;
    const cy = height / 2;
    const baseRadius = Math.min(width, height) * 0.44;
    // Group by kind so each ring's members spread evenly around their own circle,
    // with a stable per-kind angle offset so rings don't line up radially.
    const byKind = {};
    nodes.forEach((node) => {
      const kind = node.kind || 'other';
      if (!byKind[kind]) byKind[kind] = [];
      byKind[kind].push(node);
    });
    const kindOffsets = { subnet: 0, scenario: 0.3, signal: 0.6, prediction: 0.15, judge: 0.45, disposition: 0.75 };
    const positions = {};
    Object.keys(byKind).forEach((kind) => {
      const members = byKind[kind];
      const radius = baseRadius * ringRadiusFraction(kind);
      const offset = (kindOffsets[kind] != null ? kindOffsets[kind] : 0) * Math.PI;
      members.forEach((node, index) => {
        const angle = offset + (2 * Math.PI * index) / members.length - Math.PI / 2;
        positions[node.id] = {
          x: cx + radius * Math.cos(angle),
          y: cy + radius * Math.sin(angle),
        };
      });
    });
    return positions;
  }

  function setEmptyMessage(root, message, show) {
    const empty = root.querySelector('#mindmap-graph-empty');
    if (!empty) return;
    if (message) empty.textContent = message;
    empty.classList.toggle('hidden', !show);
  }

  function renderMetrics(container, metrics) {
    container.innerHTML = '';
    if (!metrics || typeof metrics !== 'object') return;
    Object.entries(metrics).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') return;
      const dt = document.createElement('dt');
      dt.textContent = key.replace(/_/g, ' ');
      const dd = document.createElement('dd');
      dd.textContent = typeof value === 'object' ? JSON.stringify(value) : String(value);
      container.appendChild(dt);
      container.appendChild(dd);
    });
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
    if (kind === 'subnet') {
      const n = metrics.event_count != null ? `${metrics.event_count} trail events` : 'subnet node';
      return `${node.label || node.id} · ${n}`;
    }
    return node.label || node.id || '';
  }

  function showDetail(panel, node) {
    if (!node) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.querySelector('#mindmap-detail-kind').textContent = node.kind || 'node';
    panel.querySelector('#mindmap-detail-title').textContent = node.label || node.id;
    panel.querySelector('#mindmap-detail-id').textContent = humanDetailLine(node);
    const metricsEl = panel.querySelector('#mindmap-detail-metrics');
    // Prefer human line; only dump sparse metrics keys that help
    const slim = {};
    const m = node.metrics || {};
    ['action', 'decision', 'event_count', 'last_event_type', 'score'].forEach(function (k) {
      if (m[k] != null && m[k] !== '') slim[k] = m[k];
    });
    renderMetrics(metricsEl, slim);
    const updated = node.updated_at ? `Updated ${node.updated_at}` : '';
    panel.querySelector('#mindmap-detail-updated').textContent = updated;
  }

  function renderGraph(root, graph) {
    const svg = root.querySelector('#mindmap-graph-svg');
    const panel = document.getElementById('mindmap-detail-panel');
    if (!svg) return;

    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const edges = Array.isArray(graph.edges) ? graph.edges : [];

    svg.innerHTML = '';
    if (!nodes.length) {
      setEmptyMessage(
        root,
        'Mindmap graph is empty — no trail, disposition, or scenario nodes yet. Data will appear as the learning loop records events.',
        true
      );
      showDetail(panel, null);
      return;
    }

    setEmptyMessage(root, '', false);

    const width = svg.clientWidth || 640;
    const height = svg.clientHeight || 360;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

    const positions = layoutNodes(nodes, width, height);
    const nodeById = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const adjacency = {};
    edges.forEach((edge) => {
      if (!adjacency[edge.source]) adjacency[edge.source] = new Set();
      if (!adjacency[edge.target]) adjacency[edge.target] = new Set();
      adjacency[edge.source].add(edge.target);
      adjacency[edge.target].add(edge.source);
    });

    const cx = width / 2;
    const cy = height / 2;

    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const coreGradient = document.createElementNS('http://www.w3.org/2000/svg', 'radialGradient');
    coreGradient.setAttribute('id', 'mindmap-core-gradient');
    coreGradient.innerHTML =
      '<stop offset="0%" stop-color="#eaf5ee" stop-opacity="0.9"/>' +
      '<stop offset="100%" stop-color="#3fc9ff" stop-opacity="0"/>';
    defs.appendChild(coreGradient);
    svg.appendChild(defs);

    // Pulsing "brain core" — always present, purely atmospheric (not a real node),
    // it's the visual anchor every edge appears to flow toward.
    const coreGlow = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    coreGlow.setAttribute('cx', cx);
    coreGlow.setAttribute('cy', cy);
    coreGlow.setAttribute('r', 26);
    coreGlow.setAttribute('class', 'mindmap-core-glow');
    const core = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    core.setAttribute('cx', cx);
    core.setAttribute('cy', cy);
    core.setAttribute('r', 7);
    core.setAttribute('class', 'mindmap-core');

    const edgeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    edgeLayer.setAttribute('class', 'mindmap-edges');
    const nodeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    nodeLayer.setAttribute('class', 'mindmap-nodes');

    const maxWeight = edges.reduce((m, e) => Math.max(m, Number(e.weight) || 1), 1);
    const edgeEls = [];
    edges.forEach((edge) => {
      const from = positions[edge.source];
      const to = positions[edge.target];
      if (!from || !to) return;
      const weight = Number(edge.weight) || 1;
      const strength = Math.max(0.35, Math.min(1, weight / maxWeight));
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', from.x);
      line.setAttribute('y1', from.y);
      line.setAttribute('x2', to.x);
      line.setAttribute('y2', to.y);
      line.setAttribute('class', 'mindmap-edge');
      line.dataset.source = edge.source;
      line.dataset.target = edge.target;
      // Energy flow toward the core — brighter, faster for higher-weight evidence.
      line.style.stroke = kindColor((nodeById[edge.target] || {}).kind);
      line.style.opacity = String(0.25 + strength * 0.35);
      line.style.animationDuration = (2.8 - strength * 1.4).toFixed(2) + 's';
      edgeLayer.appendChild(line);
      edgeEls.push(line);
    });

    let selectedId = null;

    function highlightEdges(nodeId) {
      edgeEls.forEach((line) => {
        const connected =
          line.dataset.source === nodeId || line.dataset.target === nodeId;
        line.classList.toggle('is-highlight', connected);
      });
    }

    nodes.forEach((node) => {
      const pos = positions[node.id];
      if (!pos) return;
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('class', 'mindmap-node');
      group.dataset.nodeId = node.id;

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', pos.x);
      circle.setAttribute('cy', pos.y);
      // Judges and the call (disposition) sit nearest the core and read as the
      // "decision engine" — give them more visual weight than raw evidence nodes.
      const isCore = node.kind === 'judge' || node.kind === 'disposition';
      circle.setAttribute('r', isCore ? 17 : 13);
      circle.setAttribute('fill', kindColor(node.kind));
      circle.classList.add('mindmap-node-circle');
      if (isCore) circle.classList.add('mindmap-node-circle--core');

      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', pos.x);
      label.setAttribute('y', pos.y + 28);
      label.setAttribute('text-anchor', 'middle');
      label.textContent = (node.label || node.id || '').slice(0, 18);

      group.appendChild(circle);
      group.appendChild(label);

      group.addEventListener('mouseenter', () => {
        group.classList.add('is-hovered');
        highlightEdges(node.id);
      });
      group.addEventListener('mouseleave', () => {
        group.classList.remove('is-hovered');
        highlightEdges(selectedId);
      });
      group.addEventListener('click', () => {
        selectedId = node.id;
        nodeLayer.querySelectorAll('.mindmap-node').forEach((el) => {
          el.classList.toggle('is-selected', el.dataset.nodeId === selectedId);
        });
        highlightEdges(selectedId);
        showDetail(panel, node);
      });

      nodeLayer.appendChild(group);
    });

    svg.appendChild(edgeLayer);
    svg.appendChild(coreGlow);
    svg.appendChild(core);
    svg.appendChild(nodeLayer);

    if (nodes.length === 1) {
      selectedId = nodes[0].id;
      const only = nodeLayer.querySelector('.mindmap-node');
      if (only) only.classList.add('is-selected');
      showDetail(panel, nodes[0]);
    }
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
      const resp = await fetch(api, { headers: { Accept: 'application/json' } });
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
    if (graph.scoped && !(graph.nodes || []).length) {
      setEmptyMessage(root, 'No graph edges for this focus subnet yet — trail fills as picks resolve.', true);
    } else {
      setEmptyMessage(root, '', false);
    }
    renderGraph(root, graph);
  }

  async function init() {
    const root = document.getElementById('mindmap-graph-root');
    if (!root) return;
    const toggle = document.getElementById('mindmap-graph-mobile-toggle');
    if (toggle) {
      toggle.addEventListener('click', function () {
        const expanded = root.classList.toggle('is-expanded');
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        toggle.textContent = expanded ? 'Close mind map' : 'Open mind map';
        if (expanded && !root.dataset.rendered) {
          refreshGraph();
        }
      });
    }
    if (window.matchMedia && window.matchMedia('(min-width: 481px)').matches) {
      await refreshGraph();
    }
    document.addEventListener('living-focus:change', refreshGraph);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
