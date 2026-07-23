#!/bin/sh
# Fly web process — HTTP only; essential background via BACKGROUND_ON_WEB=essential.
# Full heavy feeds (live subnets wedge) run on the worker process group when scaled:
#   fly scale count worker=1 --app subnet-dashboard
exec uvicorn server:app --host 0.0.0.0 --port 8080
