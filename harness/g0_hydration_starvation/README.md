# G0 hydration starvation harness (#1058)

Repeatable Playwright (Chromium) probe for homepage cold-load starvation.

**Not a product test.** Measure-only. Do not treat a clean local run as evidence
against host/shared-runtime contention.

## Install (venv, not requirements.txt)

```bash
source .venv/bin/activate
pip install playwright
python -m playwright install chromium
```

## Prod (read-only, twice)

```bash
python harness/g0_hydration_starvation/run_g0.py \
  --base-url https://subnet-dashboard.fly.dev \
  --run-id prod-1 \
  --out-dir artifacts/g0-baseline/prod-1

python harness/g0_hydration_starvation/run_g0.py \
  --base-url https://subnet-dashboard.fly.dev \
  --run-id prod-2 \
  --out-dir artifacts/g0-baseline/prod-2
```

If the two runs disagree, run `prod-3` and take majority. If still mixed,
report **intermittent starvation**.

## Local (instrumentation sanity only)

```bash
PORT=50745 python server.py   # leave running
python harness/g0_hydration_starvation/run_g0.py \
  --base-url http://127.0.0.1:50745 \
  --run-id local-sanity \
  --out-dir artifacts/g0-baseline/local-sanity
```

## Outputs per run

- `summary.json` / `baseline.md` — standing baseline table
- `session.har` — full HAR
- `requests.json` / `events.json` / `hero_snapshots.json` / `health_series.json`
- `console.jsonl`
- `hero_t10s.png` / `hero_t45s.png`

`HERO_COMPLETE_AT` fires when `/api/learning/stats` is parsed **and** the
tribunal hero is no longer the placeholder (`Awaiting subnet` / `data-verdict-kind=cold`).
