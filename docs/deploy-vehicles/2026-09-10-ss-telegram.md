# Telegram engagement and Subnet Summer deploy vehicle

This docs-only vehicle deploys the current main commit after merging the Subnet Summer full-desk call-leader layout and Telegram engagement-metrics refresh.

Included production changes:

- PR #1264: add graded call leaders to /subnetsummers.
- PR #1265: refresh deduplicated engagement metrics and ingest message edits/reaction updates.

Validation target: guarded Fly deployment from main, including endpoint, topology, readiness, version, cache-warm, and learning-loop checks.
