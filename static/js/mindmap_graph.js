(function () {
  'use strict';

  const KIND_COLORS = {
    subnet: '#22D3EE',
    signal: '#8B5CF6',
    judge: '#F59E0B',
    prediction: '#10B981',
    scenario: '#F97316',
    disposition: '#3B82F6',
  };

  function kindColor(kind) {
    return KIND_COLORS[kind] || '#9CA3AF';
  }

  function layoutNodes(nodes, width, height) {
    const count = nodes.length;
    if (!count) return {};
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.36;
    const positions = {};
    nodes.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / count - Math.PI / 2;
      positions[node.id] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
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

  function showDetail(panel, node) {
    if (!node) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.querySelector('#mindmap-detail-kind').textContent = node.kind || 'node';
    panel.querySelector('#mindmap-detail-title').textContent = node.label || node.id;
    panel.querySelector('#mindmap-detail-id').textContent = node.id || '';
    renderMetrics(panel.querySelector('#mindmap-detail-metrics'), node.metrics || {});
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

    const edgeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    edgeLayer.setAttribute('class', 'mindmap-edges');
    const nodeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    nodeLayer.setAttribute('class', 'mindmap-nodes');

    const edgeEls = [];
    edges.forEach((edge) => {
      const from = positions[edge.source];
      const to = positions[edge.target];
      if (!from || !to) return;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', from.x);
      line.setAttribute('y1', from.y);
      line.setAttribute('x2', to.x);
      line.setAttribute('y2', to.y);
      line.setAttribute('class', 'mindmap-edge');
      line.dataset.source = edge.source;
      line.dataset.target = edge.target;
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
      circle.setAttribute('r', 14);
      circle.setAttribute('fill', kindColor(node.kind));

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
    svg.appendChild(nodeLayer);

    if (nodes.length === 1) {
      selectedId = nodes[0].id;
      const only = nodeLayer.querySelector('.mindmap-node');
      if (only) only.classList.add('is-selected');
      showDetail(panel, nodes[0]);
    }
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

    const api = root.dataset.api || '/api/mindmap/graph';
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

  async function init() {
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

    renderGraph(root, graph);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
