# Echo Kin — SimiVision lookalike lane (pump desk)

**Status:** SHIP  
**Branch:** `cursor/echo-kin-pump-desk-1d2f`  
**Inspiration:** competitor “DNA twins / uniqueness / archetypes” framing — **not a copy**.

## Our terms (do not use competitor vocabulary)

| Theirs (avoid) | Ours |
|----------------|------|
| DNA / genes | **Pulse** (triad + flow vector) |
| DNA Twins | **Echo Kin** |
| Substance / Behaviour strands | (skip — we already have Thesis vs Flow on desk) |
| Uniqueness Score | **Signature rarity** |
| Rocket / Blue Chip / Zombie… | **Lane tags:** Coil · Quiet Load · Pressure · Lift · Drift · Hollow |

## Question we answer

> SN X is already moving — which quieter subnets share the same pulse?

## Scope

1. `internal/pump/echo_kin.py` — L1/Hamming on existing ladder `signal_snapshot` + triad (no new scorer)
2. Attach to `build_pump_alerts_desk` hero as `echo` / `lane` / `signature_rarity`
3. Homepage scan + flagship `/pump` hero UI + hydrate
4. Tests: `tests/test_echo_kin.py`

## Out of scope

- Full-universe council gene vectors
- New scoring engine
- Telegram bot posting Echo Kin (later)
- Copying competitor archetype names
