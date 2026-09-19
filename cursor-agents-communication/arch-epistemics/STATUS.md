# Arch-epistemics STATUS

- **Gate 0/0b:** CLEARED (SMOKE-001 VERIFIED)
- **C-014:** MC-validated **partial** — pending Joshua spotcheck (2026-09-19T22:10Z)
  - AFFIRM: fresh-starvation via `scores.get(netuid, -1.0)` + `ranked[:cap]` (+ write-path re-cap)
  - REFUTE: stale mtime surfacing stale scores (age gate → None)
- **bundle:** `bundles/C-014.Tracer.json`
- **pin:** `c9449d6490231373748f19f299ed19d423a1c971`
- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1294
- **last_updated:** 2026-09-19T22:10Z
