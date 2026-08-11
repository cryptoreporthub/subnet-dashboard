import type { CSSProperties, ReactNode } from 'react';

type GlassTier = 'card' | 'flat' | 'bar';

const RADIUS: Record<GlassTier, string> = {
  card: 'var(--radius-xl)',
  flat: 'var(--radius-lg)',
  bar: '0px',
};

/**
 * GlassPanel — a translucent frosted surface for the deep-space treatment.
 *
 * The shipped dashboard floats its content on glass tiers over the
 * {@link CosmicSky} substrate rather than on opaque chips. This primitive
 * captures those tiers so consumers never hand-roll the fill, blur, border and
 * glow:
 *
 * - `card` — a focal surface: a soft top-light gradient, a saturating blur and
 *   an ambient drop shadow.
 * - `flat` — a quiet secondary surface: the subtle glass fill, no blur.
 * - `bar` — a full-bleed navigation/status band: a vertical scrim over blur,
 *   squared corners, and a hairline edge.
 *
 * Every colour derives from design-system tokens (`--color-foreground`,
 * `--color-card`, `--color-border`). Positioning and sizing are the consumer's
 * job — pass them through `style`.
 */
export function GlassPanel({
  tier = 'card',
  edge = 'bottom',
  className = '',
  style,
  children,
}: {
  tier?: GlassTier;
  /** For `bar`: which side carries the hairline edge. */
  edge?: 'top' | 'bottom';
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}) {
  const hairline =
    'color-mix(in srgb, var(--color-foreground) 6%, transparent)';
  const border = 'color-mix(in srgb, var(--color-foreground) 18%, transparent)';
  const fillSubtle =
    'color-mix(in srgb, var(--color-foreground) 2.5%, transparent)';
  const fillCard = 'color-mix(in srgb, var(--color-foreground) 4%, transparent)';
  const topLight =
    'linear-gradient(180deg, color-mix(in srgb, var(--color-foreground) 6%, transparent) 0%, color-mix(in srgb, var(--color-foreground) 2%, transparent) 40%, transparent 72%)';
  const barScrim =
    'linear-gradient(180deg, color-mix(in srgb, var(--color-card) 82%, transparent) 0%, color-mix(in srgb, var(--color-card) 58%, transparent) 100%)';

  const base: CSSProperties = {
    borderRadius: RADIUS[tier],
    ...style,
  };

  const tierStyle: CSSProperties =
    tier === 'card'
      ? {
          background: `${topLight}, ${fillCard}`,
          border: `1px solid ${border}`,
          backdropFilter: 'blur(12px) saturate(1.2)',
          WebkitBackdropFilter: 'blur(12px) saturate(1.2)',
          boxShadow: `0 1px 0 ${hairline} inset, 0 24px 60px -32px color-mix(in srgb, var(--color-card) 90%, transparent)`,
        }
      : tier === 'flat'
        ? {
            background: fillSubtle,
            border: `1px solid ${border}`,
          }
        : {
            background: barScrim,
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            [edge === 'top' ? 'borderTop' : 'borderBottom']:
              `1px solid ${hairline}`,
          };

  return (
    <div className={className} style={{ ...base, ...tierStyle }}>
      {children}
    </div>
  );
}

export default GlassPanel;
