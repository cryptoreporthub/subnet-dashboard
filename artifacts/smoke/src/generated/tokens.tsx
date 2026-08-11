/* GENERATED FROM tokens.json -- DO NOT EDIT. Run scripts/build-tokens.mjs. */
// Portable design tokens (colors as hex). Web consumes the theme via
// src/index.css; mobile (Expo) and any other platform import this object so the
// whole product shares one source of truth.
export const tokens = {
  "color": {
    "light": {
      "background": "#979da2",
      "foreground": "#f2f5f8",
      "border": "#b6bcc1",
      "card": "#14181c",
      "cardForeground": "#eef2f6",
      "popover": "#14181c",
      "popoverForeground": "#eef2f6",
      "primary": "#3fd77f",
      "primaryForeground": "#04140b",
      "secondary": "#2a2f35",
      "secondaryForeground": "#e3e8ee",
      "muted": "#868c92",
      "mutedForeground": "#d7dce1",
      "accent": "#cfa54e",
      "accentForeground": "#241a06",
      "destructive": "#e05656",
      "destructiveForeground": "#ffffff",
      "input": "#b6bcc1",
      "ring": "#4fc3f7",
      "chart1": "#4fc3f7",
      "chart2": "#3fd77f",
      "chart3": "#cfa54e",
      "chart4": "#9aa3ad",
      "chart5": "#e2627c",
      "nebula": "#9d8cff",
      "sidebar": "#0f1216",
      "sidebarForeground": "#e3e8ee",
      "sidebarBorder": "#262b31",
      "sidebarPrimary": "#3fd77f",
      "sidebarPrimaryForeground": "#04140b",
      "sidebarAccent": "#1c2127",
      "sidebarAccentForeground": "#eef2f6",
      "sidebarRing": "#4fc3f7"
    },
    "dark": {
      "background": "#0b0e11",
      "foreground": "#eef2f6",
      "border": "#232830",
      "card": "#14181c",
      "cardForeground": "#eef2f6",
      "popover": "#14181c",
      "popoverForeground": "#eef2f6",
      "primary": "#3fd77f",
      "primaryForeground": "#04140b",
      "secondary": "#1b2027",
      "secondaryForeground": "#dbe2ea",
      "muted": "#171c22",
      "mutedForeground": "#98a1ab",
      "accent": "#cfa54e",
      "accentForeground": "#241a06",
      "destructive": "#ef4444",
      "destructiveForeground": "#ffffff",
      "input": "#262c34",
      "ring": "#4fc3f7",
      "chart1": "#4fc3f7",
      "chart2": "#3fd77f",
      "chart3": "#cfa54e",
      "chart4": "#9aa3ad",
      "chart5": "#e2627c",
      "nebula": "#9d8cff",
      "sidebar": "#0d1014",
      "sidebarForeground": "#dbe2ea",
      "sidebarBorder": "#232830",
      "sidebarPrimary": "#3fd77f",
      "sidebarPrimaryForeground": "#04140b",
      "sidebarAccent": "#1b2027",
      "sidebarAccentForeground": "#eef2f6",
      "sidebarRing": "#4fc3f7"
    }
  },
  "fontFamily": {
    "sans": [
      "Inter",
      "system-ui",
      "sans-serif"
    ],
    "serif": [
      "Lora",
      "Georgia",
      "serif"
    ],
    "mono": [
      "JetBrains Mono",
      "ui-monospace",
      "monospace"
    ]
  },
  "radius": "0.75rem",
  "spacing": "0.25rem"
} as const;

export type Tokens = typeof tokens;
export default tokens;
