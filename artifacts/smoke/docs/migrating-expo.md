# Migrating Expo UI to Smoke Council

Read `artifacts/smoke/docs/AGENTS.md` and
`artifacts/smoke/docs/consuming-expo.md` first. Use this guide
when an Expo app, including a fresh scaffold, has local theme, hooks, fonts, or
product-agnostic component implementations.

## Rewrite theme and font imports

Grep the Expo artifact for `@/constants/colors`, `@/hooks/useColors`, local
`useFonts` calls, and direct font imports. Read every matching scaffold and app
file before deleting anything.

- Rewrite color/theme imports to
  `@workspace/smoke/lib/native-theme` and
  `@workspace/smoke/hooks/use-colors`.
- Rewrite the root layout to use
  `@workspace/smoke/hooks/use-fonts` while preserving its
  SplashScreen gating.
- Delete app-local `constants/colors.ts` and `hooks/useColors.ts` after every
  import points at this package. Do not leave compatibility re-exports.
- Remove local palette interfaces, token mappings, font registrations, and
  color-scheme logic now supplied by this package.

## Replace product-agnostic UI

Inventory inline and app-local styled controls before migrating screens.

- Replace product-agnostic Buttons, typography, Inputs, Textareas, Fields,
  Cards, Badges, Toggles, Empty states, Spinners, and Skeletons with package
  native components.
- Keep domain-specific compositions local, but rewrite their internals to
  compose package primitives.
- Delete app-local product-agnostic components after all imports are rewritten.
- Do not import web `components/ui/*`, `styles.css`, or DOM/Tailwind code into
  React Native.

## Clean dependencies and verify

- Keep the design-system workspace package and its native peer dependencies in
  Expo `dependencies`.
- Remove dependencies used only by deleted local implementations.
- Confirm `constants/colors.ts` and `hooks/useColors.ts` are gone.
- Grep for the old local import paths and resolve every hit.
- Run Expo typecheck and the development workflow; verify the native theme,
  fonts, and one package primitive before presenting the app.

Migration is complete when Expo imports every shared visual primitive, theme,
and hook directly from `@workspace/smoke` and retains only
product-specific UI compositions locally.
