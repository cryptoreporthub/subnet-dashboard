# Migrating web UI to Smoke Council

Read `artifacts/smoke/docs/AGENTS.md` and
`artifacts/smoke/docs/consuming-web.md` first. Use this guide
when a web app, including a fresh scaffold, already has local theme or component
copies.

## Replace the local theme

Replace the app's Tailwind/theme setup with the package import from the web
consumption guide.

- Remove the app's own `@import "tailwindcss"`, plugin imports, and generated
  `:root` / `.dark` token definitions.
- Keep app-specific CSS that is not a theme or package-provided primitive.
- Keep Tailwind v3 directives and configure its package component source as
  described in the web consumption guide.

## Rewrite imports

Rewrite every local import for a module this package provides:

- `@/components/ui/<name>` →
  `@workspace/smoke/components/ui/<name>`
- `@/lib/utils` (`cn`) → `@workspace/smoke/lib/utils`
- `@/hooks/use-toast` → `@workspace/smoke/hooks/use-toast`

Judge component ownership by the imported module, not by the file doing the
import. App-specific components may remain local, but they must import shared
primitives from this package.

## Delete superseded files

- Delete package-provided files from the app's `src/components/ui/`; remove the
  directory if it becomes empty.
- Delete local `src/lib/utils.ts` when it only provided `cn`.
- Delete local `src/hooks/use-toast.ts` after every caller uses the package hook.
- Remove dependencies used only by the deleted local component library when the
  design-system package already supplies them transitively.

## Verify migration

Grep for `@/components/ui/`, `@/lib/utils`, and `@/hooks/use-toast`. Every
remaining match must refer to an app-specific module or export the package does
not provide. Run typecheck and the dev server after deleting local copies.

Migration is complete when no package-provided component, `cn`, toast hook, or
theme token block remains local.
