# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-16T00:20:00Z  
**main:** `6b37876` (#279 C1) · prod listener **live**

## One-line

**§18 COMPLETE (H1–C1). Prod: message-intel listener running; store honest-empty until group traffic. Optional: A1 conviction alert delivery secrets.**

## §17 (done)

B8–B11 + U4 merged (#267–#271, #274). F7/B12 deferred.

## §18 queue

See **`s18-automated-build-plan.md`**.

| Slice | State |
|-------|--------|
| **H1–B1** | ✅ #265–#278 |
| **C1** | ✅ **live on Fly** — `listener.reason=running`, `session=true` (#279, human bootstrap done) |
| **A1** | ✅ docs — optional human: `CONVICTION_ALERT_DELIVERY` + bot/webhook secrets |

**Prod check:** `GET /api/message-intel/status` → `live: true` · `verify_prod.sh` message-intel line green.

**Billing watch:** On-Demand **$** beyond Pro+ → tell human.
