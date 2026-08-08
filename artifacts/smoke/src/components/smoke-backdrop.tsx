import type { CSSProperties } from 'react';

/**
 * SmokeBackdrop — the signature surface of the Smoke Council system.
 *
 * A brushed-metal smoke field. Near-black chips float on top of it, so this
 * layer supplies the light, not the dark. Rendered entirely in CSS/SVG so it
 * stays crisp at any size (no grainy raster).
 *
 * The tonal structure is deliberate and was matched against the Council
 * reference capture: a mid-grey metal base that stays fairly even out to the
 * edges, a heavy dark cloud gathered in the upper centre, a broad lift through
 * the middle band where the verdict dial sits, and a shadow pooling along the
 * bottom. There is no strong corner vignette — the metal runs to the edges.
 *
 * Layers, bottom to top:
 *   1. mid-grey metal base
 *   2. the dark cloud in the upper centre
 *   3. the mid-band lift, brighter to the left
 *   4. cloud marbling (light puffs and dark hollows)
 *   5. fractal-noise turbulence: coarse drift and fine grain
 *   6. a fine vertical brush grain
 *   7. a faint cool cast up top and a warm ember undertow low
 *   8. right-edge shade and the shadow pooling at the bottom
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
      {/* metal base */}
      <div className="absolute inset-0" style={{ background: '#5f646a' }} />

      {/* the dark cloud gathered in the upper centre */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(48% 25% at 50% 14%, rgba(20,23,28,0.70) 0%, rgba(20,23,28,0.30) 54%, rgba(20,23,28,0) 80%)',
        }}
      />

      {/* mid-band lift — the metal catches the light where the dial sits */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(46% 20% at 32% 40%, rgba(224,230,236,0.10) 0%, rgba(224,230,236,0) 78%),' +
            'radial-gradient(34% 18% at 50% 47%, rgba(214,221,228,0.13) 0%, rgba(214,221,228,0) 78%)',
        }}
      />

      {/* cloud marbling — light puffs */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(30% 15% at 18% 30%, rgba(228,233,238,0.13) 0%, rgba(228,233,238,0) 72%),' +
            'radial-gradient(26% 13% at 74% 42%, rgba(220,226,231,0.09) 0%, rgba(220,226,231,0) 74%),' +
            'radial-gradient(32% 15% at 34% 62%, rgba(230,235,239,0.08) 0%, rgba(230,235,239,0) 74%),' +
            'radial-gradient(22% 11% at 88% 68%, rgba(216,222,228,0.07) 0%, rgba(216,222,228,0) 76%)',
          filter: 'blur(24px)',
        }}
      />

      {/* cloud marbling — dark hollows */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(24% 13% at 8% 56%, rgba(44,48,54,0.30) 0%, rgba(44,48,54,0) 74%),' +
            'radial-gradient(22% 12% at 92% 30%, rgba(40,44,50,0.28) 0%, rgba(40,44,50,0) 74%),' +
            'radial-gradient(28% 14% at 62% 76%, rgba(38,42,48,0.26) 0%, rgba(38,42,48,0) 76%)',
          filter: 'blur(28px)',
        }}
      />

      {/* fractal noise — coarse drift + fine grain */}
      <svg
        className="absolute inset-0 h-full w-full"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id="smoke-drift">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.004 0.006"
              numOctaves="5"
              seed="21"
              stitchTiles="stitch"
              result="noise"
            />
            <feColorMatrix in="noise" type="saturate" values="0" />
            <feComponentTransfer>
              <feFuncA type="table" tableValues="1 1" />
            </feComponentTransfer>
          </filter>
          <filter id="smoke-grain">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.75"
              numOctaves="2"
              seed="7"
              stitchTiles="stitch"
              result="noise"
            />
            <feColorMatrix in="noise" type="saturate" values="0" />
            <feComponentTransfer>
              <feFuncA type="table" tableValues="1 1" />
            </feComponentTransfer>
          </filter>
        </defs>
        <rect
          width="100%"
          height="100%"
          filter="url(#smoke-drift)"
          opacity="0.30"
          style={{ mixBlendMode: 'overlay' }}
        />
        <rect
          width="100%"
          height="100%"
          filter="url(#smoke-grain)"
          opacity="0.12"
          style={{ mixBlendMode: 'overlay' }}
        />
      </svg>

      {/* fine vertical brush grain */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'repeating-linear-gradient(90deg,' +
            'rgba(255,255,255,0.05) 0px, rgba(255,255,255,0.05) 1px,' +
            'rgba(0,0,0,0.04) 1px, rgba(0,0,0,0.04) 2px,' +
            'rgba(255,255,255,0.02) 2px, rgba(255,255,255,0.02) 4px)',
          opacity: 0.5,
        }}
      />

      {/* cool cast up top, ember undertow low */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(44% 18% at 30% 34%, rgba(116,166,204,0.08) 0%, rgba(116,166,204,0) 76%),' +
            'radial-gradient(66% 22% at 50% 99%, rgba(198,140,52,0.16) 0%, rgba(198,140,52,0) 74%)',
        }}
      />

      {/* right-edge shade and the shadow pooling at the bottom */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(40% 22% at 40% 65%, rgba(22,25,30,0.30) 0%, rgba(22,25,30,0) 80%),' +
            'radial-gradient(20% 26% at 0% 52%, rgba(24,27,32,0.26) 0%, rgba(24,27,32,0) 80%),' +
            'radial-gradient(36% 30% at 86% 40%, rgba(24,27,32,0.36) 0%, rgba(24,27,32,0) 82%),' +
            'radial-gradient(28% 48% at 100% 62%, rgba(24,27,32,0.46) 0%, rgba(24,27,32,0) 78%),' +
            'radial-gradient(36% 20% at 92% 88%, rgba(18,21,26,0.34) 0%, rgba(18,21,26,0) 80%),' +
            'radial-gradient(64% 17% at 48% 91%, rgba(14,17,21,0.58) 0%, rgba(14,17,21,0) 82%),' +
            'linear-gradient(0deg, rgba(12,15,18,0.50) 0%, rgba(12,15,18,0) 11%),' +
            'linear-gradient(270deg, rgba(26,29,34,0.10) 0%, rgba(26,29,34,0) 9%)',
        }}
      />
    </div>
  );
}
