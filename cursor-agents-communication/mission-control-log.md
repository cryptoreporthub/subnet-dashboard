# Mission Control Log

- 2026-09-30 — PR #1317 F04 P2: aligned council CAS snapshot selection with
  `load_weights()` precedence (`adversarial_state`, `soul_map_state`, root),
  added the differing dual-legacy-slot regression, and verified local focused
  persistence (32 passed), endpoint contract (148 passed), changed-file Black,
  and GitHub smoke run 36805718494 at head
  `6212dcbacf368f24086e0486ed17b71d93d6e12f`. PR remains Draft; no merge or
  deploy. Same-process-only and cache/cross-process limitations remain.
- 2026-10-01 — Post-merge provenance slice: PR #1319 adds the full `GIT_SHA` as
  the OCI image revision label and returns the full SHA from `/version`.
  Deterministic route/config tests pass (43), endpoint contract passes (148),
  and no Fly settings or deployment were changed.
