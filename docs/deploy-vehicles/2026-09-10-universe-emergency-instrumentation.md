# Universe emergency-registry instrumentation deploy vehicle

This docs-only vehicle deploys the current main commit after merging the emergency_registry fallback instrumentation.

Included production changes:

- PR #1269: Prometheus counter `subnet_universe_emergency_total{reason}` in internal/metrics.py, a logger.warning at the construction choke point, and distinct `reason` labels threaded through all four `emergency_registry()` construction sites in internal/subnet_universe.py (refresh_unresolvable, empty_membership, cold_start_no_lkg, lkg_missing_or_corrupt).

Note: this main-HEAD deploy also carries the already-merged SS Telegram vehicle (#1266, commit 7d0c16a6), which had not yet reached production as of `/version` = 2672a03.

Validation target: guarded Fly deployment from main, including endpoint, topology, readiness, version, cache-warm, and learning-loop checks. Post-deploy verification: `subnet_universe_emergency_total` visible in /metrics.
