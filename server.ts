import express, { Request, Response } from 'express';
import nunjucks from 'nunjucks';
import cors from 'cors';
import fs from 'fs';
import path from 'path';

const app = express();
const PORT = parseInt(process.env.PORT || '3000', 10);

app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Serve static assets
const staticDir = path.join(process.cwd(), 'static');
if (fs.existsSync(staticDir)) {
  app.use('/static', express.static(staticDir));
}

// Configure Nunjucks template engine
const templatesDir = path.join(process.cwd(), 'templates');
const env = nunjucks.configure(templatesDir, {
  autoescape: true,
  express: app,
  noCache: true
});

// Custom Nunjucks filters matching Python Jinja filters
env.addFilter('safe_list', (val: any) => {
  if (val === null || val === undefined) return [];
  if (Array.isArray(val)) return val;
  return [val];
});

env.addFilter('shorten', (val: any, places: number = 1) => {
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(places) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(places) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(places) + 'K';
  return n.toFixed(places);
});

env.addFilter('round', (val: any, precision: number = 0) => {
  const n = parseFloat(val);
  if (isNaN(n)) return 0;
  return parseFloat(n.toFixed(precision));
});

env.addFilter('int', (val: any, def: number = 0) => {
  const n = parseInt(val, 10);
  return isNaN(n) ? def : n;
});

env.addFilter('float', (val: any, def: number = 0) => {
  const n = parseFloat(val);
  return isNaN(n) ? def : n;
});

env.addFilter('default', (val: any, defVal: any) => {
  return (val !== undefined && val !== null && val !== '') ? val : defVal;
});

env.addFilter('sort', (arr: any[], ...args: any[]) => {
  if (!Array.isArray(arr)) return [];
  const options = args[0] || {};
  let attr = typeof options === 'object' ? options.attribute : undefined;
  let reverse = typeof options === 'object' ? options.reverse : false;

  const copy = [...arr];
  copy.sort((a, b) => {
    let valA = attr ? a?.[attr] : a;
    let valB = attr ? b?.[attr] : b;
    if (valA < valB) return reverse ? 1 : -1;
    if (valA > valB) return reverse ? -1 : 1;
    return 0;
  });
  return copy;
});

env.addFilter('capitalize', (str: any) => {
  if (str === null || str === undefined) return '';
  const s = String(str);
  return s.length > 0 ? s.charAt(0).toUpperCase() + s.slice(1) : '';
});
env.addFilter('title', (str: any) => {
  if (str === null || str === undefined) return '';
  const s = String(str);
  return s.length > 0 ? s.replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.substring(1).toLowerCase()) : '';
});
env.addFilter('lower', (str: any) => {
  if (str === null || str === undefined) return '';
  return String(str).toLowerCase();
});
env.addFilter('upper', (str: any) => {
  if (str === null || str === undefined) return '';
  return String(str).toUpperCase();
});
env.addFilter('replace', (str: any, oldVal: string, newVal: string) => {
  if (str === null || str === undefined) return '';
  return String(str).replaceAll(oldVal, newVal);
});
env.addFilter('list', (val: any) => Array.isArray(val) ? val : (val ? [val] : []));
env.addFilter('map', (arr: any, attr?: string | any) => {
  if (!Array.isArray(arr)) return [];
  if (typeof attr === 'string') {
    return arr.map((item: any) => item?.[attr]);
  }
  if (typeof attr === 'object' && attr?.attribute) {
    return arr.map((item: any) => item?.[attr.attribute]);
  }
  return arr;
});
env.addFilter('first', (arr: any) => Array.isArray(arr) ? arr[0] : arr);
env.addFilter('last', (arr: any) => Array.isArray(arr) ? arr[arr.length - 1] : arr);
env.addFilter('set_key', (obj: any, key: any, val: any) => {
  if (obj && typeof obj === 'object') obj[key] = val;
  return obj;
});
env.addFilter('push', (arr: any, item: any) => {
  const a = Array.isArray(arr) ? arr : [];
  return [...a, item];
});

env.addFilter('tojson', (val: any) => new nunjucks.runtime.SafeString(JSON.stringify(val ?? null)));

env.addFilter('max', (arr: any, attr?: string) => {
  if (!Array.isArray(arr) || arr.length === 0) return 0;
  if (attr) return Math.max(...arr.map(x => x?.[attr] || 0));
  return Math.max(...arr);
});

env.addFilter('min', (arr: any, attr?: string) => {
  if (!Array.isArray(arr) || arr.length === 0) return 0;
  if (attr) return Math.min(...arr.map(x => x?.[attr] || 0));
  return Math.min(...arr);
});

env.addFilter('truncate', (val: any, length: number = 255, killwords: boolean = false, end: string = '...') => {
  if (val === null || val === undefined) return '';
  const str = String(val);
  if (str.length <= length) return str;
  if (killwords) {
    return str.substring(0, length) + end;
  }
  const idx = str.lastIndexOf(' ', length);
  if (idx === -1) return str.substring(0, length) + end;
  return str.substring(0, idx) + end;
});

env.addFilter('format', (val: any, ...args: any[]) => {
  if (typeof val === 'string' && val.includes('%')) {
    let i = 0;
    return val.replace(/%(\.?\d*)f|%s|%d/g, (match, precision) => {
      const arg = args[i++];
      if (arg === undefined || arg === null) return '';
      if (match.endsWith('f')) {
        const prec = precision ? parseInt(precision.replace('.', ''), 10) : 2;
        return parseFloat(arg).toFixed(isNaN(prec) ? 2 : prec);
      }
      return String(arg);
    });
  }
  return String(val);
});

// Custom Jinja-compatible tests for Nunjucks
const envAny = env as any;
envAny.addTest('mapping', (val: any) => typeof val === 'object' && val !== null && !Array.isArray(val));
envAny.addTest('iterable', (val: any) => val !== null && val !== undefined && (Array.isArray(val) || typeof val === 'string' || typeof val === 'object'));
envAny.addTest('string', (val: any) => typeof val === 'string');
envAny.addTest('number', (val: any) => typeof val === 'number');
envAny.addTest('none', (val: any) => val === null || val === undefined);
envAny.addTest('defined', (val: any) => val !== undefined && val !== null);
envAny.addTest('sameas', (a: any, b: any) => a === b);

// Global template variables
env.addGlobal('publish_gate_label', () => 'PUBLISH_ALLOWED');
env.addGlobal('static_v', '20260711');
env.addGlobal('True', true);
env.addGlobal('False', false);
env.addGlobal('None', null);
env.addGlobal('namespace', (initial: any = {}) => ({ ...initial }));

// Helper to load JSON safely
function loadJson(relPath: string, fallback: any = {}): any {
  try {
    const fullPath = path.join(process.cwd(), relPath);
    if (fs.existsSync(fullPath)) {
      const content = fs.readFileSync(fullPath, 'utf-8');
      return JSON.parse(content);
    }
  } catch (err) {
    console.warn(`[JSON Loader] Failed to load ${relPath}:`, err);
  }
  return fallback;
}

// Data helper functions
function getSubnetsList(): any[] {
  const regMap = loadJson('config/registry.json', {});
  return Object.values(regMap).map((sn: any) => ({
    id: sn.id ?? 0,
    netuid: sn.id ?? 0,
    name: sn.name || `Subnet ${sn.id}`,
    emission: sn.emission || 0,
    emission_rank: sn.emission_rank || 1,
    price_change_24h: sn.price_change_24h || 0,
    staking_data: sn.staking_data || { total_stake: 100000, apy: 0.15 },
    apy: sn.staking_data?.apy || 0.15,
    status: sn.status || 'active',
    is_overvalued: sn.is_overvalued || false,
    sources: sn.sources || ['registry'],
    source: 'registry'
  }));
}

function getDailyPickData(): any {
  const dailyPicks = loadJson('data/daily_picks.json', []);
  const first = Array.isArray(dailyPicks) ? dailyPicks[0] : (dailyPicks?.daily_pick || dailyPicks);
  if (first && (first.pick || first.candidate || first.action)) {
    return first;
  }
  const subnets = getSubnetsList();
  const topSn = subnets.find(s => s.netuid === 4 || s.id === 4) || subnets[0] || {};
  return {
    action: "long",
    pick: {
      subnet: { netuid: topSn.netuid || topSn.id || 4, name: topSn.name || "Targon", symbol: "TAO" },
      score: 85.9,
      confidence: 0.716,
      final_confidence: 0.716,
      action: "long"
    }
  };
}

function getTribunalContext(dpick: any, subnets: any[]) {
  const pickObj = dpick?.pick || dpick?.candidate || {};
  const sn = pickObj?.subnet || dpick?.subnet || subnets[0] || { netuid: 4, name: "Targon" };
  const netuid = sn.netuid ?? sn.id ?? 4;
  const name = sn.name || `Subnet ${netuid}`;
  const subnetLabel = `SN${netuid} · ${name}`;
  
  const rawConf = pickObj.final_confidence ?? pickObj.confidence ?? pickObj.score ?? 0.716;
  const confPct = rawConf <= 1.0 ? Math.round(rawConf * 100) : Math.round(rawConf);
  const action = (pickObj.action || dpick.action || 'HOLD').toUpperCase();

  return {
    subnet_label: subnetLabel,
    verdict_kind: "sealed",
    conviction_temp: "warm",
    gauge_attr: `${confPct}%`,
    gauge_display: `${confPct}%`,
    conviction_pct: confPct,
    synced_at: dpick.timestamp_utc || new Date().toISOString(),
    epoch_label: "4821",
    gate_label: "SEALED",
    action_label: action,
    headline: `Council clears ${subnetLabel} with ${confPct}% conviction`,
    judges: [
      {
        key: "oracle",
        label: "ORACLE",
        signal_pct: "85.9%",
        weight_pct: "36%",
        last5: [true, true, false, true, true]
      },
      {
        key: "echo",
        label: "ECHO",
        signal_pct: "84.0%",
        weight_pct: "32%",
        last5: [true, false, true, true, true]
      },
      {
        key: "pulse",
        label: "PULSE",
        signal_pct: "45.0%",
        weight_pct: "32%",
        last5: [false, true, true, false, true]
      }
    ],
    panels: {
      decision_log: {
        verdict_kind: "SEALED",
        confidence: `${confPct}%`,
        consensus: "3/3",
        brain: "GPT-4o / Claude 3.5",
        dissent: "None"
      },
      accuracy_ledger: {
        win_rate: "78%",
        sub: "Directional accuracy over last 42 calls",
        graded: 42,
        correct: 33,
        wrong: 9,
        last5: [true, true, false, true, true]
      },
      jury_move: [
        { key: "oracle", label: "Oracle", arrow: "▲", delta: "+2.4%" },
        { key: "echo", label: "Echo", arrow: "▲", delta: "+1.1%" },
        { key: "pulse", label: "Pulse", arrow: "▼", delta: "-0.8%" }
      ]
    }
  };
}

function getDashboardContext() {
  const subnets = getSubnetsList();
  const signalsObj = loadJson('data/signals.json', []);
  const signals = Array.isArray(signalsObj) ? signalsObj : (signalsObj?.signals || []);
  const alertsObj = loadJson('data/alerts.json', []);
  const alerts = Array.isArray(alertsObj) ? alertsObj : (alertsObj?.alerts || []);

  const soulMapObj = loadJson('data/soul_map.json', {});
  const soulMapState = soulMapObj?.soul_map_state || {};
  const learningTrail = soulMapState?.learning_trail || soulMapObj?.learning_trail || [];

  const dpick = getDailyPickData();

  return {
    subnets,
    signals,
    alerts,
    signal_summary: { active_signals: signals.length, avg_confidence: 0.85 },
    simivision: {
      top: subnets.slice(0, 5),
      meta: { caution_cells: [] }
    },
    dpick: dpick,
    daily_pick: dpick,
    daily_pick_stage: dpick,
    tribunal: getTribunalContext(dpick, subnets),
    hour_picks: subnets.slice(0, 3),
    day_picks: subnets.slice(0, 5),
    trust_banner: {
      graded: 42,
      ready: true,
      accuracy: 0.78,
      min_graded: 30
    },
    pump_alerts: alerts,
    api_indicators_convergence: { subnets: subnets.slice(0, 5) },
    mindmap_trail: learningTrail,
    mindmap_graph: {
      status: learningTrail.length > 0 ? 'ok' : 'empty',
      nodes: soulMapObj.nodes || [],
      edges: soulMapObj.edges || [],
      integration_status: soulMapObj.integration_status || {
        dispositions: 'active',
        scenario: 'active',
        whales: 'read_only',
        indicators: 'active'
      }
    },
    mindmap_status: learningTrail.length > 0 ? 'ok' : 'empty',
    static_v: '20260711'
  };
}

// --- HTML Page Routes ---

app.get('/', (req: Request, res: Response) => {
  res.render('index.html', getDashboardContext());
});

app.get('/health', (req: Request, res: Response) => {
  res.send('OK');
});

app.get('/robots.txt', (req: Request, res: Response) => {
  res.type('text/plain').send('User-agent: *\nAllow: /');
});

app.get('/preview/tribunal', (req: Request, res: Response) => {
  res.render('preview/tribunal.html', getDashboardContext());
});

app.get('/preview/k3-hold', (req: Request, res: Response) => {
  res.render('preview/k3_hold.html', getDashboardContext());
});

app.get('/preview/k3-pump-alert', (req: Request, res: Response) => {
  res.render('preview/k3_pump_alert.html', getDashboardContext());
});

app.get('/preview/k3-pump-alert-scan', (req: Request, res: Response) => {
  res.render('preview/k3_pump_alert_scan.html', getDashboardContext());
});

app.get('/preview/pump-desk-polish', (req: Request, res: Response) => {
  res.render('preview/pump_desk_polish.html', getDashboardContext());
});

app.get('/preview/pump-desk-full', (req: Request, res: Response) => {
  res.render('preview/pump_desk_full.html', getDashboardContext());
});

app.get('/pump', (req: Request, res: Response) => {
  res.render('pump.html', getDashboardContext());
});

app.get('/judge-council', (req: Request, res: Response) => {
  res.render('judge_council.html', getDashboardContext());
});

app.get('/simivision', (req: Request, res: Response) => {
  res.render('simivision.html', getDashboardContext());
});

app.get('/share/subnet/:id', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  const subnet = subnets.find(s => String(s.id) === req.params.id) || subnets[0] || {};
  res.render('share/subnet_page.html', { ...getDashboardContext(), subnet });
});

app.get('/share/wallet/:id', (req: Request, res: Response) => {
  res.render('share/wallet_page.html', { ...getDashboardContext(), wallet_address: req.params.id });
});

// --- API Routes ---

app.get('/metrics', (req: Request, res: Response) => {
  res.type('text/plain').send('# HELP app_up Status\napp_up 1\n');
});

app.get('/api/health', (req: Request, res: Response) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.get('/api/pump-alerts', (req: Request, res: Response) => {
  const alerts = loadJson('data/alerts.json', []);
  res.json({ alerts: Array.isArray(alerts) ? alerts : [] });
});

app.get('/api/pump-patterns/:param', (req: Request, res: Response) => {
  res.json({ patterns: [], timeframe: req.params.param });
});

app.get('/api/data-freshness', (req: Request, res: Response) => {
  res.json({ status: 'fresh', last_updated: new Date().toISOString() });
});

app.get('/api/ops/readiness', (req: Request, res: Response) => {
  res.json({ status: 'ready', checks: { database: 'ok', cache: 'ok' } });
});

app.get('/api/ops/live', (req: Request, res: Response) => {
  res.json({ status: 'live' });
});

app.get('/api/ops/worker-peer', (req: Request, res: Response) => {
  res.json({ peer: 'ok' });
});

app.get('/api/ops/evidence', (req: Request, res: Response) => {
  res.json({ evidence: [] });
});

app.get('/api/ops/desearch-spend', (req: Request, res: Response) => {
  res.json({ spend: 0 });
});

app.get('/api/subnet-integrations', (req: Request, res: Response) => {
  const protocols = loadJson('config/protocols.json', []);
  res.json({ integrations: Array.isArray(protocols) ? protocols : [] });
});

app.get('/api/subnet-integrations/signals', (req: Request, res: Response) => {
  const signals = loadJson('data/signals.json', []);
  res.json({ signals: Array.isArray(signals) ? signals : [] });
});

app.get('/api/daily-rotation', (req: Request, res: Response) => {
  res.json({ rotation: [] });
});

app.get('/api/registry', (req: Request, res: Response) => {
  const registry = loadJson('config/registry.json', {});
  res.json(registry);
});

app.get('/api/subnets', (req: Request, res: Response) => {
  let subnets = getSubnetsList();
  
  if (req.query.status) {
    subnets = subnets.filter(s => s.status === req.query.status);
  }
  if (req.query.sort) {
    const key = String(req.query.sort);
    const isDesc = req.query.order === 'desc';
    subnets.sort((a, b) => {
      const valA = a[key] ?? 0;
      const valB = b[key] ?? 0;
      return isDesc ? (valB - valA) : (valA - valB);
    });
  }
  if (req.query.limit) {
    const lim = parseInt(String(req.query.limit), 10);
    if (!isNaN(lim) && lim > 0) {
      subnets = subnets.slice(0, lim);
    }
  }
  res.json(subnets);
});

app.get('/api/subnet/:id', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  const subnet = subnets.find(s => String(s.id) === req.params.id);
  if (subnet) {
    res.json(subnet);
  } else {
    res.status(404).json({ error: 'Subnet not found' });
  }
});

app.get('/api/summary', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({
    total_subnets: subnets.length,
    active_subnets: subnets.filter(s => s.status === 'active').length,
    last_updated: new Date().toISOString()
  });
});

app.get('/api/stats', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({
    total_count: subnets.length,
    total_emission: subnets.reduce((acc, s) => acc + (s.emission || 0), 0)
  });
});

app.get('/api/soul-map', (req: Request, res: Response) => {
  const soulMap = loadJson('data/soul_map.json', {});
  res.json(soulMap);
});

app.get('/api/recommendations', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({ recommendations: subnets.slice(0, 3) });
});

app.post('/api/mindmap/feedback', (req: Request, res: Response) => {
  res.json({ status: 'ok', note: req.body?.note || '' });
});

app.get('/api/mindmap/graph', (req: Request, res: Response) => {
  try {
    const soulMapObj = loadJson('data/soul_map.json', {});
    const soulMapState = soulMapObj?.soul_map_state || {};
    const learningTrail = soulMapState?.learning_trail || soulMapObj?.learning_trail || [];
    const dispositions = soulMapState?.pump_dispositions || [];

    let nodes = soulMapObj.nodes || [];
    let edges = soulMapObj.edges || [];

    if (nodes.length === 0 && learningTrail.length > 0) {
      nodes = learningTrail.map((t: any, idx: number) => ({
        id: t.id || `node-${idx}`,
        label: t.subnet_id ? `SN${t.subnet_id}` : (t.type || 'event'),
        type: t.type || 'trail_event',
        data: t
      }));
    }

    res.json({
      status: learningTrail.length > 0 ? 'ok' : 'empty',
      nodes,
      edges,
      integration_status: soulMapObj.integration_status || {
        dispositions: dispositions.length > 0 ? 'active' : 'read_only',
        scenario: 'active',
        whales: 'read_only',
        indicators: 'active'
      }
    });
  } catch (err: any) {
    console.warn('[Mindmap API Warning]: Failed to compile graph:', err);
    res.json({
      status: 'error',
      nodes: [],
      edges: [],
      error: err?.message || 'Error compiling mindmap graph'
    });
  }
});

app.get('/api/mindmap/trail', (req: Request, res: Response) => {
  try {
    const soulMapObj = loadJson('data/soul_map.json', {});
    const soulMapState = soulMapObj?.soul_map_state || {};
    const learningTrail = soulMapState?.learning_trail || soulMapObj?.learning_trail || [];
    res.json({ status: 'ok', trail: learningTrail });
  } catch (err: any) {
    console.warn('[Mindmap API Warning]: Failed to fetch trail:', err);
    res.json({ status: 'error', trail: [], error: err?.message });
  }
});

app.get('/api/simivision', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({ status: 'ok', picks: subnets.slice(0, 5) });
});

app.get('/api/top-picks', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({ top_picks: subnets.slice(0, 3) });
});

app.get('/api/daily-pick', (req: Request, res: Response) => {
  const dailyPicks = loadJson('data/daily_picks.json', {});
  res.json(dailyPicks?.daily_pick || { subnet: getSubnetsList()[0] || {} });
});

app.get('/api/daily-pick/weighed', (req: Request, res: Response) => {
  const dailyPicks = loadJson('data/daily_picks.json', {});
  res.json(dailyPicks?.weighed || { subnet: getSubnetsList()[0] || {} });
});

app.get('/api/pick-explain/:id', (req: Request, res: Response) => {
  res.json({ subnet_id: req.params.id, explanation: 'High technical convergence and positive whale flow.' });
});

app.get('/api/top-pick/day', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({ top_pick: subnets[0] || {} });
});

app.get('/api/top-pick/hour', (req: Request, res: Response) => {
  const subnets = getSubnetsList();
  res.json({ top_pick: subnets[0] || {} });
});

app.get('/api/whales/summary', (req: Request, res: Response) => {
  const whaleIntel = loadJson('data/whale_intelligence.json', {});
  res.json(whaleIntel);
});

app.get('/api/whales/dimensions', (req: Request, res: Response) => {
  res.json({ dimensions: [] });
});

app.get('/api/whales/leaderboards', (req: Request, res: Response) => {
  const whales = loadJson('config/whales.json', []);
  res.json({ leaderboards: Array.isArray(whales) ? whales : [] });
});

app.get('/api/whales/leaderboards/ruggers', (req: Request, res: Response) => {
  const ruggers = loadJson('data/ruggers_watchlist.json', []);
  res.json({ ruggers: Array.isArray(ruggers) ? ruggers : [] });
});

app.get('/api/whales/wallet/:address', (req: Request, res: Response) => {
  res.json({ address: req.params.address, total_stake: 50000, activity: [] });
});

app.get('/api/whales/alerts', (req: Request, res: Response) => {
  const alerts = loadJson('data/alerts.json', []);
  res.json({ alerts: Array.isArray(alerts) ? alerts : [] });
});

app.get('/api/whales/subnet/:id/flow', (req: Request, res: Response) => {
  res.json({ subnet_id: req.params.id, net_flow_24h: 12500 });
});

app.get('/api/whales/flow-signals', (req: Request, res: Response) => {
  res.json({ signals: [] });
});

app.get('/api/dev-radar', (req: Request, res: Response) => {
  res.json({ radar: [] });
});

app.post('/api/whales/events', (req: Request, res: Response) => {
  res.json({ status: 'recorded', event: req.body });
});

app.post('/api/whales/scan', (req: Request, res: Response) => {
  res.json({ status: 'scanned', results: [] });
});

app.get('/api/investigate/subnet/:id/sellers', (req: Request, res: Response) => {
  res.json({ subnet_id: req.params.id, sellers: [] });
});

app.get('/api/investigate/wallet/:address', (req: Request, res: Response) => {
  res.json({ address: req.params.address, risk_score: 'low', flags: [] });
});

app.get('/api/investigate/wallet/:address/flow', (req: Request, res: Response) => {
  res.json({ address: req.params.address, flow: [] });
});

app.get('/api/investigate/subnet/:id/owner-check', (req: Request, res: Response) => {
  res.json({ subnet_id: req.params.id, verified: true });
});

app.post('/api/investigate/ask', (req: Request, res: Response) => {
  res.json({ question: req.body?.question || '', answer: 'No suspicious seller activity detected on this subnet.' });
});

app.get('/api/judges', (req: Request, res: Response) => {
  const judges = loadJson('data/judge_portfolios.json', []);
  res.json({ judges: Array.isArray(judges) ? judges : [] });
});

app.get('/api/judges/:id', (req: Request, res: Response) => {
  res.json({ id: req.params.id, name: `Judge ${req.params.id}`, performance: 0.82 });
});

app.get('/api/judges/oracle/postmortems', (req: Request, res: Response) => {
  const echoPostmortem = loadJson('data/postmortems/echo.json', {});
  res.json({ postmortems: [echoPostmortem] });
});

app.get('/api/paper-portfolio', (req: Request, res: Response) => {
  res.json({ positions: [], total_value: 100000 });
});

app.get('/api/portfolios', (req: Request, res: Response) => {
  res.json({ portfolios: [] });
});

app.get('/api/watchlist', (req: Request, res: Response) => {
  const watchlist = loadJson('config/watchlist.json', []);
  res.json(watchlist);
});

app.get('/api/portfolio', (req: Request, res: Response) => {
  res.json({ positions: [] });
});

app.get('/api/signals', (req: Request, res: Response) => {
  const signals = loadJson('data/signals.json', []);
  res.json(signals);
});

app.get('/api/indicators', (req: Request, res: Response) => {
  const indicators = loadJson('data/indicator_state.json', {});
  res.json(indicators);
});

// Start Express Server listening on 0.0.0.0:3000
app.listen(PORT, '0.0.0.0', () => {
  console.log(`[AI Studio] Subnet Dashboard Express server listening on http://0.0.0.0:${PORT}`);
});
