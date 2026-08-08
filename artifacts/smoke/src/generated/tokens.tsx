/* GENERATED FROM tokens.json -- DO NOT EDIT. Run scripts/build-tokens.mjs. */
// Portable design tokens (colors as hex). Web consumes the theme via
// src/index.css; mobile (Expo) and any other platform import this object so the
// whole product shares one source of truth.
export const tokens = {
  "color": {
    "light": {
      "background": "#eef1f5",
      "foreground": "#11161d",
      "border": "#c9d2dc",
      "card": "#ffffff",
      "cardForeground": "#11161d",
      "popover": "#ffffff",
      "popoverForeground": "#11161d",
      "primary": "#0ea96b",
      "primaryForeground": "#f3fffa",
      "secondary": "#e3e9f0",
      "secondaryForeground": "#1b2430",
      "muted": "#e6ebf1",
      "mutedForeground": "#5b6673",
      "accent": "#e8930c",
      "accentForeground": "#221302",
      "destructive": "#d64545",
      "destructiveForeground": "#ffffff",
      "input": "#cdd6e0",
      "ring": "#14b8c0",
      "chart1": "#0ea7d8",
      "chart2": "#0ea96b",
      "chart3": "#e8930c",
      "chart4": "#7181a0",
      "chart5": "#d64f7d",
      "sidebar": "#f4f6f9",
      "sidebarForeground": "#313c4b",
      "sidebarBorder": "#d3dbe4",
      "sidebarPrimary": "#0ea96b",
      "sidebarPrimaryForeground": "#f3fffa",
      "sidebarAccent": "#e7edf3",
      "sidebarAccentForeground": "#1b2430",
      "sidebarRing": "#14b8c0"
    },
    "dark": {
      "background": "#0a0d13",
      "foreground": "#eaf0f8",
      "border": "#1f2937",
      "card": "#10151d",
      "cardForeground": "#eaf0f8",
      "popover": "#10151d",
      "popoverForeground": "#eaf0f8",
      "primary": "#2fd37b",
      "primaryForeground": "#04140b",
      "secondary": "#16202c",
      "secondaryForeground": "#d7e0ec",
      "muted": "#151d29",
      "mutedForeground": "#8b98ab",
      "accent": "#f5a524",
      "accentForeground": "#1a1002",
      "destructive": "#ef4444",
      "destructiveForeground": "#ffffff",
      "input": "#232e3c",
      "ring": "#3ee6c8",
      "chart1": "#37b6f2",
      "chart2": "#2fd37b",
      "chart3": "#f5a524",
      "chart4": "#7c94b8",
      "chart5": "#e2627c",
      "sidebar": "#0d1219",
      "sidebarForeground": "#d7e0ec",
      "sidebarBorder": "#1f2937",
      "sidebarPrimary": "#2fd37b",
      "sidebarPrimaryForeground": "#04140b",
      "sidebarAccent": "#16202c",
      "sidebarAccentForeground": "#eaf0f8",
      "sidebarRing": "#3ee6c8"
    }
  },
  "fontFamily": {
    "sans": [
      "Space Grotesk",
      "Inter",
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
