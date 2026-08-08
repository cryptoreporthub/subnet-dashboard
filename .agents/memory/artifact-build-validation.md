---
name: Validating artifact builds (smoke / mockup-sandbox)
description: How to actually run a build or typecheck for the artifacts, and why the obvious commands fail.
---

## `pnpm run typecheck` cannot run

The artifacts declare a `typecheck` script (`tsc -p tsconfig.json --noEmit`) but **TypeScript is not installed** anywhere in the workspace — not at the root, not per-artifact. The script always fails with `sh: 1: tsc: not found`.

**Why:** the artifact scaffolds ship the script without the devDependency.

**How to apply:** don't treat a failing `typecheck` as a regression you introduced. Validate with `vite build` instead (it catches import/syntax breakage), or install TypeScript first if real type coverage is needed.

## Builds need env vars that only the workflow normally supplies

Both `artifacts/smoke` and `artifacts/mockup-sandbox` have vite configs that **throw at config-load time** on missing env vars, so `pnpm run build` fails before compiling anything:

- `PORT` — required by both
- `BASE_PATH` — required by `mockup-sandbox`

**Why:** the configs hard-require them rather than defaulting, and the managed workflows inject them; a bare shell has neither.

**How to apply:** run builds as
`PORT=3001 BASE_PATH=/ pnpm run build` (smoke) and
`PORT=3002 BASE_PATH=/__mockup/ pnpm run build` (mockup-sandbox).
The error surfaces one var at a time, so read the *head* of the output — the tail is just an unhelpful vite stack.
