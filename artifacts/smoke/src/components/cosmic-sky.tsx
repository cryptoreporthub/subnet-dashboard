import type { CSSProperties } from 'react';

/**
 * CosmicSky — the deep-space substrate that overlays the Smoke field.
 *
 * The shipped Council surface layers a nebula-and-starfield sky on top of the
 * brushed-metal {@link SmokeBackdrop} so the metal atmosphere still ghosts
 * through at low opacity. This component reproduces that treatment as a
 * product-agnostic primitive.
 *
 * Every colour is a design-system token — signal cyan (`--color-chart-1`),
 * cosmic violet (`--color-nebula`), ember amber (`--color-accent`), rose
 * (`--color-chart-5`) and seafoam (`--color-primary`) — read through
 * `color-mix` so the nebula clouds and stars stay on-palette. Layer it after
 * `SmokeBackdrop` inside the same positioned container.
 */
export function CosmicSky({
  className = '',
  style,
}: {
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
      style={style}
    >
      {/* dark space veil — dims the smoke metal so the sky reads while the
          brushed atmosphere still ghosts through */}
      <div
        className="absolute inset-0"
        style={{ background: 'color-mix(in srgb, var(--color-card) 86%, transparent)' }}
      />

      {/* nebula clouds */}
      <div
        className="absolute inset-0"
        style={{
          background: [
            'radial-gradient(38% 22% at 8% 12%, color-mix(in srgb, var(--color-chart-1) 22%, transparent), transparent 70%)',
            'radial-gradient(44% 26% at 92% 16%, color-mix(in srgb, var(--color-nebula) 26%, transparent), transparent 70%)',
            'radial-gradient(40% 24% at 80% 84%, color-mix(in srgb, var(--color-accent) 18%, transparent), transparent 70%)',
            'radial-gradient(34% 20% at 16% 76%, color-mix(in srgb, var(--color-chart-5) 16%, transparent), transparent 70%)',
            'radial-gradient(52% 32% at 55% 45%, color-mix(in srgb, var(--color-primary) 10%, transparent), transparent 70%)',
          ].join(','),
        }}
      />

      {/* starfield */}
      <div
        className="absolute inset-0"
        style={{
          opacity: 0.7,
          backgroundSize: '200px 200px',
          backgroundImage: [
            'radial-gradient(1.6px 1.6px at 7% 5%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 15% 13%, var(--color-chart-1) 50%, transparent 51%)',
            'radial-gradient(2px 2px at 22% 9%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 31% 18%, var(--color-chart-1) 50%, transparent 51%)',
            'radial-gradient(1.6px 1.6px at 38% 6%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 47% 15%, var(--color-chart-1) 50%, transparent 51%)',
            'radial-gradient(1.2px 1.2px at 56% 8%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 64% 20%, var(--color-chart-1) 50%, transparent 51%)',
            'radial-gradient(1.6px 1.6px at 72% 5%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 81% 16%, var(--color-chart-1) 50%, transparent 51%)',
            'radial-gradient(1.2px 1.2px at 89% 10%, var(--color-foreground) 50%, transparent 51%)',
            'radial-gradient(1px 1px at 95% 22%, var(--color-chart-1) 50%, transparent 51%)',
          ].join(','),
        }}
      />
    </div>
  );
}

export default CosmicSky;
