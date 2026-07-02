# Premium Dashboard Redesign — Interface Contract

> **PREDICTIVE APP**: every output is framed as *"predicted to move +X% within N hours"*. Never use past tense ("price moved +X% after signal"). The learning loop persists predictions to `data/predictions.json` and resolves them over time, updating Council expert weights (correct = +0.02, wrong = -0.03).

This document is the single source of truth for the 2-worker parallel build.
- **Worker 1 (backend-intelligence)** owns `server.py` computation + API endpoints (this contract's *backend* side).
- **Worker 2 (frontend-premium-ui)** owns `templates/index.html` and must consume **exactly** the Jinja variable names defined below.

## 1. Template context variables (rendered into `templates/index.html` by the `/` route)

All variables are injected by `_build_premium_context(subnets)` and passed to `templates.TemplateResponse`.

| Variable | Type | Description |
|---|---|---|
| `subnets` | `list[dict]` | Full live subnet list (from taomarketcap). Each has `netuid, name, emission, apy, volume, market_cap, price, price_change_24h, price_change_7d, price_change_30d, status, sector`. |
| `data_source` | `str` | `"live"` or `"cache"` — provenance of subnet data. |
| `mindmap` | `dict` | Existing mindmap summary (expert weights + top picks). |
| `learning_stats` | `dict` | Existing learning stats. |
| `simivision` | `dict` | Existing SimiVision data. |
| `rotation_tokens` | `list` | Existing rotation tokens. |
| `simivision_picks` | `list[dict]` | Top 6 picks. See §2. |
| `undervalued_radar` | `list[dict]` | Top 8 undervalued subnets with `undervalued_score`, `rank`. |
| `technical_indicators` | `list[dict]` | Per-subnet indicator panel. See §3. |
| `market_intelligence` | `dict` | Market scanner summary. See §4. |
| `staking_analytics` | `dict` | Staking & yield. See §5. |
| `council_weights` | `list[dict]` | `[{expert, weight, bias}]`. |
| `expert_weights` | `dict` | Raw `{alpha, beta, gamma}` weights. |
| `mindmap_trail` | `list[dict]` | Learning trail `[{time, subnet, evidence, signal, decision, prediction, judge}]`. |
| `signal_impact` | `list[dict]` | Per-subnet signal impact engine output. See §6. |
| `patterns` | `list[dict]` | Per-subnet pattern recognition. See §7. |
| `predictions` | `list[dict]` | Active predictions. See §8. |
| `learning_metrics` | `dict` | Learning loop metrics. See §9. |
| `social_sentiment` | `list[dict]` | Per-subnet social sentiment. See §10. |
| `indicators_convergence` | `dict` | `{oversold, overbought}` convergence for top subnet. See §11. |

## 2. `simivision_picks[*]`

```
{
  rank, netuid, name, emission, apy, price, price_change_24h,
  conviction,            # 0-95
  recommendation,        # "BUY" | "HOLD" | "WATCH" | "SELL"
  reasons,               # list[str], up to 3
  sparkline,             # list[float], last 12 closes
  hot:   {active, score, reasons, label},   # label = "HOT" or null
  sell:  {active, score, reasons, label},   # label = "SELL ALERT" or null
  prediction: {...},     # see §8
  signal_impact: {...}   # see §6
}
```
**Rule**: SELL ALERT wins over HOT — when `sell.active` is true, `hot.active` is forced false and `hot.suppressed_by = "SELL ALERT"`.

## 3. `technical_indicators[*]`

```
{
  netuid, name,
  indicators: {
    rsi:        {value, signal},            # signal: overbought|oversold|neutral
    stochastic: {k, d, signal},
    bollinger:  {upper, middle, lower, width, signal},
    mfi:        {mfi, signal},
    cci:        {cci, signal},
    williams_r: {williams_r, signal},
    keltner:    {upper, middle, lower, signal},
    macd:       {macd, signal, histogram, crossover},  # crossover: bullish|bearish|neutral
    ma_cross:   {...},
    history_source,  # "cached" | "synthetic"
    history_length
  },
  convergence: {...},   # see §11
  hot: {...}, sell: {...}
}
```
**Fallback**: when no candle history exists, a synthetic series is derived from `price` + 24h/7d/30d changes, and simplified RSI is used.

## 4. `market_intelligence`

```
{total, avg_change_24h, gainers, losers,
 top_gainer: {name, netuid, change},
 top_loser:  {name, netuid, change},
 avg_apy, total_volume, total_market_cap, breadth}   # breadth: bullish|bearish|neutral
```

## 5. `staking_analytics`

```
{top_yield: [{netuid, name, apy, emission, total_stake, tao_liquidity, alpha_liquidity, yield_score}],
 total_stake, avg_apy, subnet_count}
```

## 6. `signal_impact[*]`

```
{
  netuid, name,
  impacts: [{signal_type, description, direction, magnitude_pct, freshness, predicted_move}],
  net_predicted_pct,     # signed
  net_direction,         # bullish|bearish|neutral
  hot_active, sell_active,
  dominant               # "SELL ALERT" | "HOT" | null
}
```
`predicted_move` strings always read: `"predicted to move +X% within N hours"`.

## 7. `patterns[*]`

```
{netuid, name, patterns: [{pattern, type, description, confidence}]}
```
Pattern types (7): `bullish_engulfing, bearish_engulfing, hammer, shooting_star, doji, double_top, double_bottom` (plus `none` / `insufficient_data` fallbacks).

## 8. `predictions[*]`

```
{
  id, netuid, name, direction,   # up|down
  predicted_pct,                 # signed
  horizon_hours,
  reference_price, created_at, resolve_at, status,  # pending|resolved
  signal_source,
  statement,                     # "predicted to move +X% within N hours"
  # on resolution: actual_pct, correct, resolved_at
}
```

## 9. `learning_metrics`

```
{
  expert_weights, total_records,
  predictions_pending, predictions_resolved, correct, wrong, accuracy,
  deltas: {correct: 0.02, wrong: -0.03},
  recent_resolutions: [{name, predicted_pct, actual_pct, correct, statement}],
  last_updated
}
```

## 10. `social_sentiment[*]`

```
{netuid, name, score, label, mentions, feed: [{source, sentiment, text, mentions}]}
```
`label`: bullish|bearish|neutral. Sources: twitter, discord, reddit.

## 11. `indicators_convergence`

```
{
  oversold:   {type, direction, count, total, agreement, indicators, convergent},
  overbought: {type, direction, count, total, agreement, indicators, convergent}
}
```
`convergent` is true when ≥3 of 7 oscillators agree.

## 12. API endpoints

| Endpoint | Method | Returns |
|---|---|---|
| `/api/predictions` | GET | `{predictions, resolved, stats}` |
| `/api/learning-metrics` | GET | learning_metrics (§9) |
| `/api/indicators-convergence` | GET | `{subnets: [{netuid, name, oversold, overbought}]}` |

## 13. Frontend design contract (Worker 2)

- **Fonts**: Space Grotesk (display), Inter (body), JetBrains Mono (data) via Google Fonts.
- **Theme**: dark — bg `#0a0b14`, cards `#111320`, accent `#00ff6a`, negative `#ff4444`, neutral `#ffaa00`.
- **Cards**: 16px border radius, green border, hover glow.
- **Charts**: Chart.js CDN; inline SVG sparklines.
- **HOT tag**: orange glowing pill. **SELL ALERT**: red glowing pill. SELL wins over HOT.
- **13 sections**: Header (logo + LIVE pill), Hero metric + chart, SimiVision Top Picks, Undervalued Radar, Technical Indicators, Market Intelligence, Staking & Yield, Council/Soul Map weights, Mind Map learning trail, Signal Impact + Patterns + Predictive Engine + Learning Loop, Social Sentiment, SimiVision Chat, Footer status strip.
- **Vanilla JS only**, all CSS/JS inline in `templates/index.html`.
