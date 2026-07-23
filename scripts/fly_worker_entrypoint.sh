#!/bin/sh
# Fly worker process — resolver, pump ladder, whale warm, live feed (no HTTP).
exec python -m internal.worker
