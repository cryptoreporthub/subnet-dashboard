#!/bin/sh
# v1: colocate worker on web machine (shared data_volume; CI scales to 1 machine).
set -e
RUN_MODE=worker python -m internal.worker &
exec env RUN_MODE=web BACKGROUND_ON_WEB=off uvicorn server:app --host 0.0.0.0 --port 8080
