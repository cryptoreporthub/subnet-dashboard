# Implementation Directive v2.1 — Intelligence-Loop Investigation
**Received:** 2026-08-23 21:01 PT · **Supersedes:** `saga/implementation-directive-2026-08-24.md` (v1) · Deltas merged into body 2026-08-23 21:15 PT
**Provenance:** Grok 4.6 planning run → Composer implements after approval → Luna reviews AC/honesty → Gemini browser verification (never Sonnet)
**Status:** Current source of truth per issuer.

See the investigation notes in `docs/intel-loop-p0a-universe-gate.md` (written during implementation) for the recorded P0-A decision gate.

The full v2.1 body is the chat handover of 2026-08-23 21:15 PT (deltas folded, appendix removed). Implementation follows that body: P0-A investigation before membership change; additive observability; independent P0-B freshness, P0-C `/subnetsummer` fallback, P1 `/api/subnets` metadata, P2 Telegram document-only.

Non-negotiables:
- GitHub `main` is source of truth. Do not reset/rebase/stash/overwrite divergent checkout.
- Do not restart the pump scan loop before investigating universe and health.
- Do not change inline-worker topology.
- Do not rename or remove existing API fields.
- Do not enable the Telegram listener without an explicit human decision.
- Do not modify client hydration unless browser evidence proves a client-side defect.
- Preserve honest empty, stale, degraded, and unavailable states.
