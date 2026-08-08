import type { CSSProperties } from 'react';

/**
 * SmokeBackdrop — the signature atmospheric layer of the Smoke Council system.
 *
 * A smoky, organic, near-void backdrop rendered entirely in CSS/SVG so it stays
 * crisp at any size (no grainy raster). It layers, bottom to top:
 *   1. base deep-navy-charcoal wash
 *   2. blurred radial nebula blobs (cool steel + cyan, warm ember rising low)
 *   3. an SVG feTurbulence "smoke drift" texture
 *   4. a faint dot grid
 *   5. a soft vignette to focus the centre
 *
 * Glass panels float above it and let it show through the frosted blur.
 */
export function SmokeBackdrop({
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
      {/* base wash */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 90% at 50% 8%, #141a26 0%, #0b0e15 42%, #080a10 100%)',
        }}
      />

      {/* cold steel / cyan nebula — upper field */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(52% 40% at 16% 12%, rgba(55,182,242,0.20) 0%, rgba(55,182,242,0.0) 70%),' +
            'radial-gradient(60% 46% at 86% 6%, rgba(124,148,184,0.16) 0%, rgba(124,148,184,0) 72%),' +
            'radial-gradient(70% 60% at 50% 30%, rgba(36,42,58,0.55) 0%, rgba(36,42,58,0) 78%)',
          filter: 'blur(6px)',
        }}
      />

      {/* soft grey smoke puffs mid-field */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(40% 30% at 22% 48%, rgba(180,196,214,0.10) 0%, rgba(180,196,214,0) 70%),' +
            'radial-gradient(46% 34% at 72% 52%, rgba(140,158,182,0.09) 0%, rgba(140,158,182,0) 72%)',
          filter: 'blur(22px)',
        }}
      />

      {/* ember-amber undertow rising from the bottom edge */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(70% 42% at 50% 104%, rgba(245,165,36,0.30) 0%, rgba(245,165,36,0.10) 42%, rgba(245,165,36,0) 72%),' +
            'radial-gradient(44% 30% at 18% 108%, rgba(245,165,36,0.20) 0%, rgba(245,165,36,0) 70%),' +
            'radial-gradient(44% 30% at 12% 92%, rgba(230,120,40,0.16) 0%, rgba(230,120,40,0) 72%)',
          filter: 'blur(2px)',
        }}
      />

      {/* organic smoke drift — SVG turbulence, softly blended */}
      <svg
        className="absolute inset-0 h-full w-full"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id="smoke-drift">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.0065 0.0085"
              numOctaves="4"
              seed="12"
              stitchTiles="stitch"
              result="noise"
            />
            <feColorMatrix
              in="noise"
              type="matrix"
              values="0 0 0 0 0.62
                      0 0 0 0 0.68
                      0 0 0 0 0.78
                      0 0 0 0.5 0"
              result="tint"
            />
            <feGaussianBlur in="tint" stdDeviation="6" />
          </filter>
        </defs>
        <rect
          width="100%"
          height="100%"
          filter="url(#smoke-drift)"
          opacity="0.22"
          style={{ mixBlendMode: 'screen' }}
        />
      </svg>

      {/* faint dot grid */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'radial-gradient(rgba(255,255,255,0.08) 1px, transparent 1.4px)',
          backgroundSize: '22px 22px',
          maskImage:
            'radial-gradient(120% 100% at 50% 0%, black 40%, transparent 90%)',
          WebkitMaskImage:
            'radial-gradient(120% 100% at 50% 0%, black 40%, transparent 90%)',
          opacity: 0.5,
        }}
      />

      {/* vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 90% at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,0.55) 100%)',
        }}
      />
    </div>
  );
}
