# Claude pack 2 — FULL function bodies + full matrix + #720 status

Paste this **entire** message to Claude. Nothing truncated after Judges.

**Checked:** 2026-08-01 ~15:30 UTC against workspace `cockpit_hydrate.js` + `gh pr view 720`.

---

## (1) HERO — full function bodies

### `confTier` (cockpit_hydrate.js ~139–150)

```javascript
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
```

Note: `Number(null)` → `0`, so callers that pass `0` for missing also land in `tier-red` / 0%.

### `shouldApplyDailyPickPayload` (cockpit_hydrate.js ~1123–1137) — COMPLETE

```javascript
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
```

**Threshold certified:**
1. Reject non-object / pending / timeout / error
2. Reject older-than-SSR by `generated_at` ISO ms (`incomingAt < ssrAt`)
3. Reject HOLD that would downgrade SSR LONG when no pick and not newer
4. Does **not** gate on confidence missing vs zero — that is display-layer only (AC2/AC3)

Tight enough for staleness / anti-wipe; **not** the missing≠zero fix.

### `patchK3DossierFromPayload` (cockpit_hydrate.js ~1202–1375) — COMPLETE, no elision

```javascript
function patchK3DossierFromPayload(payload) {
  if (!payload || !document.getElementById('k3-dossier')) return false;
  if (!shouldApplyDailyPickPayload(payload)) return false;
  var brief = payload.brief || {};
  var pick = payload.pick;
  var cand = payload.candidate;
  var active = pick || cand;
  var sn = (active && active.subnet) || {};
  var confSrc = active || payload;
  var finalConf = confSrc.final_confidence != null ? confSrc.final_confidence : confSrc.confidence;
  var fc = confTier(finalConf != null ? finalConf : 0);
  var actRaw = String(payload.action || 'HOLD').toUpperCase();
  if (actRaw === 'BUY') actRaw = 'LONG';
  var snLabel = sn.name || (sn.netuid != null ? 'SN' + sn.netuid : '');

  if (brief.move && actRaw === 'LONG') {
    setText('k3-call-headline', brief.move);
    var headline = document.getElementById('k3-call-headline');
    if (headline) {
      headline.className = 'k3-call-headline k3-call-headline--' + (brief.tone || 'neutral');
    }
  } else if (snLabel) {
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
  if (claimHeadName && snLabel) {
    claimHeadName.textContent = snLabel;
  }
  if (typeof window.k3SyncNetuidBand === 'function') {
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
  if (actionBadge) {
    actionBadge.hidden = false;
    actionBadge.textContent = actRaw === 'LONG' ? 'LONG' : actRaw === 'SHORT' ? 'SHORT' : actRaw || 'HOLD';
    actionBadge.className =
      'k3-badge ' + (actRaw === 'LONG' ? 'buy' : actRaw === 'SHORT' ? 'sell' : 'hold');
  }
  syncK3GlowTier(fc.conf, payload.action);
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
    driversHost.innerHTML = '';
    driversHost.hidden = true;
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
  if (orb && fc.conf != null) {
    var tens = Math.floor(fc.conf / 10);
    var ones = fc.conf % 10;
    orb.innerHTML =
      (tens > 0 ? '<span class="digit-tens">' + tens + '</span>' : '') +
      '<span class="digit-ones">' + ones + '</span>';
  }
  patchK3ConvictionRing(fc.conf);

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
  return true;
}
```

**Missing≠zero is buildable without schema change:**
- Detect missing: `final_confidence == null && confidence == null` (and SSR: `conviction_raw is none`)
- Today both paths coerce missing → `0` / `conviction_pct = 0` → orb shows `0` digits (or SSR hides digits only when `conviction_pct > 0`, but label still says “conviction” and ring at 0%)
- Fix: branch on missing → idle/resolving chrome; branch on explicit `0` → zero-conviction chrome. No new API fields required.

### SSR twin (`council_stage.html` ~50–57, ~578–588)

```jinja
{% set conviction_raw = conf_src.final_confidence if conf_src and conf_src.final_confidence is not none else (conf_src.confidence if conf_src and conf_src.confidence is not none else (conf_src.conviction if conf_src and conf_src.conviction is not none else none)) %}
{% if conviction_raw is not none and conviction_raw|float <= 1.0 and conviction_raw|float >= 0.0 %}
  {% set conviction_pct = (conviction_raw|float * 100)|round|int %}
{% elif conviction_raw is not none %}
  {% set conviction_pct = conviction_raw|int %}
{% else %}
  {% set conviction_pct = 0 %}
{% endif %}
```

Orb digits only if `conviction_pct > 0`; else label falls through to `"conviction"`. Still conflates missing with zero for ring offset / glow. Accuracy already gated on `trust_banner.ready` → `cal_acc = none` (~81–92). Horizon: `dpick.time_horizon|default(dpick.horizon|default('24h'))` (~69).

---

## (2) MINDMAP — FULL matrix (continues past Judges)

| Source | Writer | Store | API | UI | Closes loop? |
|--------|--------|-------|-----|-----|--------------|
| Council / daily pick | `prediction_loop` + trail append | `predictions.json` + `soul_map.learning_trail` | `/api/daily-pick`, `/api/mindmap/trail` | `renderDailyPick`; Living Focus | **YES** |
| trail_bus (generic) | `trail_bus.emit_*` → `MindmapBridge.append_learning_trail` | `soul_map.json` `learning_trail` | `/api/mindmap/trail`, `/api/mindmap/state`, feeds graph | `renderTrail`; LF; `mindmap_graph.js` | **YES** (evidence bus) |
| **Telegram Pulse / message_intel** | `message_intel/soul_sync` emit disposition/conviction/signal | MI DB + soul_map MI dispositions | `/api/message-intel`; guarded panel summary; graph MI dispositions | proof/MI panels; graph | **PARTIAL** — trail/graph yes; author-trust loop after **#721** (still OPEN); LB-8 SelfLearning still quarantined |
| Judges (Oracle/Echo/Pulse) | `judges/tracker` → emit_judge_pnl/postmortem | portfolios + trail | judges/postmortems APIs; panel summaries | Living Focus judges; mindmap state | **YES after #720 merges** — see §3; **NOT closed on current main** |
| **Expert weights** | resolver / `nudge_expert` / LearningEngine → emit_weight_change | soul_map weights | `/api/learning/stats`, `/api/mindmap/summary` expert_weights | Bench / `renderCouncilWeights`; summary insights | **YES** |
| **Dispositions / scenario** | selector emit; scenario emit + aggregator `_trail_from_scenario_memory` | dispositions / scenario_memory JSON | graph dispositions; trail derive; scenario API | graph nodes; LF chips | **Display + trail YES**; **scoring WEAK** — outcomes often not in scorer. UI: “context only” unless §30 LB-5/6 |
| **Pump Desk leads** | pump soul_sync emits | pump state + trail | `/api/pump-alerts`; mindmap pump summaries; graph pump_dispositions | pump desk UI; graph | **PARTIAL** — parallel product UI; trail emit yes |
| Whales / indicators | graph loaders only (no trail_bus writer) | whale/indicator engines | `/api/mindmap/graph` overlays | `mindmap_graph.js` | **NO** trail loop — read-only overlay |

Aggregator: `collect_trail_events` merges soul_map + predictions + scenario (`mindmap_aggregator.py`).

---

## (2b) Five known gaps — explicit status

| Gap | Status |
|-----|--------|
| Stub conviction `50.0` on `/api/mindmap/summary` | **FIXED in API.** `_mindmap_conviction_block` (`internal/learning/routes.py` ~174–204): daily-pick conf or `{data_available: false, current: null}`. UI must honor `data_available`. |
| LB-11 duplicate trail fetch | **OPEN / PARTIAL.** Hydrate fetches `/api/mindmap/trail?limit=20` (~3610). LF uses cache if fresh else fetches `?limit=40`; listens `home:hydrate-trail`. Race if LF before cache fill → second fetch. |
| `/api/mindmap/graph` contract test | **MISSING.** `tests/test_endpoint_contract.py` has `GET /api/mindmap/summary` only — **no** graph or trail in CONTRACT. |
| Dispositions/scenario scoring vs display | **Display+trail yes; scoring weak.** Honest “context only” copy still an AC. |
| `MindmapBridge.get_brain_recommendations()` | **Heuristic registry fallback still present** (`internal/council/mindmap_bridge.py` ~58–121): emission/social rules → accumulate/hold/reduce. Empty registry → `{data_available: false, reason: "no_registry_recommendations"}` (LB-10). **Not** live council output. |

---

## (3) #720 merge status (live `gh` check)

```text
#719 soul_map cache        — OPEN, not merged
#720 Judges weights        — OPEN, MERGEABLE, CI smoke SUCCESS, mergedAt: null
                             URL: https://github.com/cryptoreporthub/subnet-dashboard/pull/720
#721 MI author trust       — OPEN, not merged
#722 board/model-guide     — OPEN (Agent L docs)
#723 hero/mindmap handoffs — OPEN (this docs branch)
```

**Do not credit Judges loop as closed on main until #720 merges.**

---

## Suggested re-gate one-liner

```text
READY FOR COMPOSER — hero first (cursor/hero-a-tier-ground-up-1d2f). Mindmap shared-file Composer BLOCKED until Agent L Phase C or human defers. Judges loop credit blocked until #720 merges.
```

Hero: PASS (AC2/AC3 = missing≠zero in SSR + `finalConf != null ? finalConf : 0`; AC4 CSS; AC5 `trust_banner.ready`; AC6 done; AC1 verify in babysit).  
Mindmap: PASS for audit completeness; Composer hold on shared files; Judges closed-loop AC depends on #720.
