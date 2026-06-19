# Deployment Guide — Subnet Dashboard

This document covers how to deploy, configure, and operate the Subnet Dashboard with the Outcome-Driven Adversarial Intelligence Layer (SimiVision Legendary Edition).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

The dashboard will be available at `http://127.0.0.1:5000`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | HTTP port for the Flask server. |
| `ENABLE_BACKGROUND_SYNC` | `true` | Start the freshness and adversarial background loops. Set to `false` for tests or one-off CLI usage. |
| `REFRESH_MINUTES` | `15` | How often the adversarial scheduler evaluates new outcomes. |
| `MAX_BACKOFF_MINUTES` | `240` | Maximum scheduler backoff after repeated failures. |
| `PROTOCOLS_PATH` | `config/protocols.json` | Protocol watchlist configuration. |
| `REGISTRY_PATH` | `config/registry.json` | Subnet registry data source. |
| `SOUL_MAP_PATH` | `data/soul_map.json` | Persistence file for verdicts, weights, and scheduler state. |

## Production deployment

The repository is configured for [Fly.io](https://fly.io). The GitHub Actions workflow in `.github/workflows/fly-deploy.yml` deploys automatically on pushes to `main`.

```bash
flyctl deploy --remote-only
```

Use gunicorn for non-Fly production hosts:

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT server:app
```

## Adversarial scheduler

The scheduler runs in a background thread and repeatedly:

1. Loads the latest subnet registry.
2. Synthesizes or reuses selector decisions.
3. Judges each decision against the current outcome.
4. Updates council weights and expert track records.
5. Persists the learning trail to `data/soul_map.json`.

On failure the scheduler uses exponential backoff (starting at `REFRESH_MINUTES` and capped at `MAX_BACKOFF_MINUTES`).

### Disable in tests

Set `ENABLE_BACKGROUND_SYNC=false` or `app.config["TESTING"] = True` to prevent the scheduler from starting automatically.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/simivision` | Top SimiVision signals enriched with council weights and expert track records. |
| `GET /api/simivision/<netuid>/trace` | Deep trace for a single signal including judge verdict and learning trail. |
| `GET /api/simivision/learning-trail` | Global learning trail, council weights, and expert track records. |
| `GET /api/simivision/scheduler` | Current scheduler state, refresh interval, and backoff status. |

## Testing

Install test dependencies (already included in `requirements.txt`):

```bash
pip install -r requirements.txt
```

Run the full suite:

```bash
pytest tests/ -q
```

Run a specific module:

```bash
pytest tests/test_adversarial_layer.py -q
pytest tests/test_simivision.py -q
```

## Data persistence

- `AdversarialJudge(persist=False)` is used by the request-time signal pipeline so that web requests never block on disk I/O.
- `AdversarialScheduler` creates the judge with `persist=True` so the background learning loop writes state.
- The `soul_map.json` file is created automatically on first scheduler run.
