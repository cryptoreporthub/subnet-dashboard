# Subnet Dashboard Master Plan

## Repo
- `cryptoreporthub/subnet-dashboard`

## Phase Order
1. J → Accuracy Fix + Tests
2. H-full → Premium UI cockpit restoration
3. K → CI Quality Gates
4. L → Real-time signals & alerts

## Phase Responsibilities
### J
- Accuracy fixes and test coverage.

### H-full
- Restore the premium UI cockpit on the homepage.
- Frontend-heavy work only.
- Keep the UI honest and production-safe.

### K
- CI quality gates.
- Validation and safety checks.

### L
- Real-time signals and alerts.
- Backend-heavy work only.

## Sequencing Rule
- Later phases must not overlap unless explicitly approved.
- H-full should precede L for the current handoff.

## Notes
- Keep the dashboard minimal, honest, and behavior-preserving.
- Do not introduce fake live data.
- Extended history and contracts: `docs/master-plan-merged.md`.
