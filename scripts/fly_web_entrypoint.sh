#!/bin/sh
# Single process on 1GB Fly — uvicorn + background in one process (BACKGROUND_ON_WEB=on).
# ponytail: colocated worker subprocess OOMs 1GB (2× CPython + pandas/live_subnets).
# internal.worker remains for future 2GB / separate-machine split.
exec uvicorn server:app --host 0.0.0.0 --port 8080
