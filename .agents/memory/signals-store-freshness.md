---
name: Data freshness safeguards
description: Durable rules for keeping live dashboard data fresh without masking stalled workers
---

# Data freshness safeguards

- Read-only dashboard data should self-heal when its cache is empty or stale, but concurrent refreshes must collapse into one operation and slow refreshes must preserve the last usable payload.
  - **Why:** HTTP success alone can hide an empty cache or turn a transiently slow feed into a blank dashboard.
  - **How to apply:** refresh based on age, single-flight the work, and return stale data with an explicit health marker on timeout.
- Worker health must be measured from real progress, not merely a running flag or periodic liveness tick; recovery must never create overlapping workers.
  - **Why:** a blocked worker can otherwise keep reporting healthy while starving downstream grading.
  - **How to apply:** update health on actual work, stop and join before replacement, or refuse replacement while the old worker is alive.