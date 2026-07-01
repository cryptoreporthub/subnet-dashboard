# Deploy Notes

## Deployment Status

- **Last Updated**: 2026-06-26
- **Frontend Fix**: API fetching enabled
- **Status**: Deployed

## API Endpoints

All endpoints are live and returning data from `taomarketcap`:
- `/api/subnets` - 129 subnets
- `/api/simivision` - Top performers
- `/api/rotation-tokens` - Rotation tokens
- `/api/mindmap/summary` - Mindmap data
- `/api/learning/stats` - Learning stats
## Fly Deploy Failure — Root Cause & Fix (2026-07-01)

### Symptom
GitHub Actions deploy runs (#265–#267) failed with exit code 1. The live site
(subnet-dashboard.fly.dev) kept serving the older image (no `/api/freshness` or
`/api/pick-history` endpoints → 404).

### Root cause (confirmed from CI logs)
The Docker build, image push, and registry steps all **succeeded**. The failure
happened at the final deploy step:

```
Error: Process group 'app' needs volumes with name 'data_volume' to fulfill
mounts defined in fly.toml; Run `fly volume create data_volume -r REGION -n COUNT`
for the following regions and counts: sjc=2
```

`fly.toml` declares a `[mounts]` block (`source = "data_volume"`,
`destination = "/app/data"`) for persistent runtime/learning data, but the named
volume did **not** exist on the Fly app. Fly refuses to start the new machine
group until the mount can be satisfied. Region **sjc**, count **2** (required to
satisfy `min_machines_running = 1` during a rolling deploy: one volume for the
old machine, one for the new).

### What was NOT the problem (verified)
- **telethon on Python 3.12-slim**: installs and imports cleanly (telethon
  1.44.0). Not a compatibility issue.
- **Node.js 18 in the Dockerfile**: the build completed fine; it was only unused
  dead weight (no `package.json`, no npm build step). Removed anyway to speed up
  builds and drop the Node 18 EOL deprecation noise.
- **Compile errors**: `py_compile server.py` and `compileall internal/` pass.

### Fix applied in this change
1. **Dockerfile**: removed the unused Node.js/npm install block (pure Python app).
2. **`.github/workflows/fly.yml`**: added an idempotent "Ensure data_volume
   exists" step that runs before `flyctl deploy`. It lists existing volumes and,
   if fewer than 2 `data_volume` volumes exist in `sjc`, creates them with
   `flyctl volumes create data_volume --app subnet-dashboard --region sjc -n 2`.
   On subsequent runs it is a no-op. This makes the deploy self-healing so it no
   longer depends on a manual one-time volume creation.
3. **`fly.toml`**: made the volume-creation comment concrete (region `sjc`,
   count `2`).

### Manual fallback (if you prefer to create the volume by hand)
```bash
fly volumes create data_volume --app subnet-dashboard --region sjc -n 2
```
Then push to `main` (or merge the PR) to trigger a deploy.

### Verification (after a successful deploy)
```bash
curl https://subnet-dashboard.fly.dev/health            # -> OK
curl https://subnet-dashboard.fly.dev/api/freshness     # -> JSON with timestamps
curl https://subnet-dashboard.fly.dev/api/pick-history  # -> JSON
curl https://subnet-dashboard.fly.dev/                  # -> 200 homepage
```
All four were verified locally against `uvicorn server:app` before pushing.
