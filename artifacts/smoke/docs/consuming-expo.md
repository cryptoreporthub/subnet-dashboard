# Consuming Smoke Council in Expo apps

Read `artifacts/smoke/docs/AGENTS.md` first. React Native does
not consume the web CSS or DOM components. It imports portable tokens, native
theme/hooks, and native components directly from this package. If the Expo app
still contains scaffolded or existing local theme/hooks/components, also read
`artifacts/smoke/docs/migrating-expo.md` before writing UI.

## Native theme and fonts

Build the shared light/dark palette, numeric radius and spacing conversion, and
registered typography names in `src/lib/native-theme.tsx`. Convert CSS lengths
once inside this package:

```tsx
import { tokens } from "@workspace/smoke/tokens";

const radius = tokens.radius.endsWith("rem")
  ? Number.parseFloat(tokens.radius) * 16
  : Number.parseFloat(tokens.radius);
```

Export `useColors` from `src/hooks/use-colors.tsx`. Export a font hook from
`src/hooks/use-fonts.tsx` that loads every required weight through `useFonts` and
returns `fontsLoaded` and `fontError`. Use exact registered names such as
`Inter_400Regular`, not CSS family names.

Expo imports these concrete paths directly:

```tsx
import { nativeTheme } from "@workspace/smoke/lib/native-theme";
import { useColors } from "@workspace/smoke/hooks/use-colors";
import { useDesignSystemFonts } from "@workspace/smoke/hooks/use-fonts";
```

Keep the root layout's existing SplashScreen gating around the shared font
hook's `fontsLoaded` and `fontError` result.

## Native components

Before writing screens, inventory the app's visual building blocks and add the
product-agnostic families it needs under `src/components/native/`. Typical
families include Button (including `size="icon"`), typography, Input, Textarea,
Label and Field, Card, Badge, Toggle or ToggleGroup, Empty, Spinner, and
Skeleton.

When `src/components/ui/` has a web counterpart, match its family exports, prop
names, variants, sizes, defaults, and state semantics wherever React Native
supports them. Implement with native primitives and document platform-required
differences in the base `AGENTS.md` inventory.

Import native primitives directly:

```tsx
import { Badge } from "@workspace/smoke/components/native/badge";
import { Button } from "@workspace/smoke/components/native/button";
import { Card } from "@workspace/smoke/components/native/card";
```

Keep product data, navigation, state, and domain compositions in Expo. A
pet-adoption `DogCard`, for example, stays app-owned but composes package Card,
Button, Badge, and typography primitives.

## Dependencies and assets

When native package source imports `react-native`, Expo modules, or font
packages, declare compatible versions in this package's peer and development
dependencies and in the consuming Expo artifact's dependencies.

Metro resolves the workspace package through pnpm symlinks. Do not copy source
or token values. Loose binary assets may still need copying into Expo because
Metro does not watch sibling artifact folders by default.

Set `app.json`'s literal `splash.backgroundColor` from
`tokens.color.light.background` and keep it synchronized when that token changes.

## Verify

Import and render
`@workspace/smoke/components/native/button`, then run Expo
typecheck and the development workflow. The import, native theme, and font hook
must resolve before broader screen work begins.
