import type { CSSProperties, ReactNode } from 'react';

type VerdictGaugeProps = {
  /** Outer diameter of the bezel, in px. */
  size?: number;
  /** Bezel thickness as a fraction of the radius. */
  ringRatio?: number;
  /** Render the sunburst rays behind the bezel. */
  rays?: boolean;
  /** Render the dashed orbit arc behind the bezel. */
  orbit?: boolean;
  /** Stacked inside the dark disc — figures, labels, pills, in caller order. */
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
};

/**
 * VerdictGauge — the dial at the heart of the Council.
 *
 * A thick brushed-silver bezel ring around a dark disc, lit from the lower left
 * so the metal reads as turned rather than painted. Faint rays radiate out
 * behind it and a dashed orbit arc sweeps the lower right.
 *
 * The disc is a stacking context, not a fixed template: the caller supplies the
 * children and controls their order. Children may extend past the disc — the
 * LONG pill on the Council screen deliberately crosses the bezel — because
 * nothing here clips.
 */
export function VerdictGauge({
  size = 274,
  ringRatio = 0.25,
  rays = true,
  orbit = true,
  children,
  className = '',
  style,
}: VerdictGaugeProps) {
  const ring = Math.round((size / 2) * ringRatio);
  const burst = Math.round(size * 1.62);
  const c = burst / 2;
  const rayInner = size * 0.44;
  const rayOuter = size * 0.57;

  return (
    <div
      className={`relative select-none ${className}`}
      style={{ width: size, height: size, ...style }}
    >
      {/* sunburst rays + dashed orbit, behind the bezel */}
      {(rays || orbit) && (
        <svg
          className="pointer-events-none absolute"
          width={burst}
          height={burst}
          viewBox={`0 0 ${burst} ${burst}`}
          style={{
            left: '50%',
            top: '50%',
            transform: 'translate(-50%, -50%)',
          }}
        >
          {rays &&
            Array.from({ length: 72 }, (_, i) => {
              const deg = (360 / 72) * i;
              const rad = ((deg - 90) * Math.PI) / 180;
              // Rays fade out toward the upper right, matching the bezel light.
              const fade = 0.5 + 0.5 * Math.cos(((deg - 205) * Math.PI) / 180);
              return (
                <line
                  key={i}
                  x1={c + rayInner * Math.cos(rad)}
                  y1={c + rayInner * Math.sin(rad)}
                  x2={c + rayOuter * Math.cos(rad)}
                  y2={c + rayOuter * Math.sin(rad)}
                  stroke={`rgba(240,244,248,${(0.02 + fade * 0.05).toFixed(3)})`}
                  strokeWidth={1}
                />
              );
            })}
          {orbit && (
            <>
              <circle
                cx={c}
                cy={c}
                r={size * 0.6}
                fill="none"
                stroke="rgba(158,202,231,0.26)"
                strokeWidth={1.5}
                strokeDasharray="7 12"
                strokeLinecap="round"
                transform={`rotate(20 ${c} ${c})`}
                clipPath="url(#vg-orbit-clip)"
              />
              <defs>
                <clipPath id="vg-orbit-clip">
                  {/* lower-right quadrant only */}
                  <rect x={c} y={c} width={burst / 2} height={burst / 2} />
                </clipPath>
              </defs>
            </>
          )}
        </svg>
      )}

      {/* brushed-silver bezel */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          // An even silver ring with a single soft shadowed dip toward the
          // lower left, where the smoke banks up against it. Sampled off the
          // Council reference rather than styled freehand — the ring reads as
          // machined metal, not chrome, so it never outshines the cyan verdict.
          background:
            'conic-gradient(from 0deg,' +
            '#cdd2d6 0deg,' +
            '#d6dbdf 45deg,' +
            '#d9dee2 90deg,' +
            '#dbe0e4 135deg,' +
            '#dfe4e8 165deg,' +
            '#d0d5d9 180deg,' +
            '#a9aeb3 196deg,' +
            '#9ea3a8 210deg,' +
            '#9a9fa4 225deg,' +
            '#9ea3a8 240deg,' +
            '#adb2b7 255deg,' +
            '#cbd0d4 272deg,' +
            '#cdd2d6 300deg,' +
            '#d0d5d9 330deg,' +
            '#cdd2d6 360deg)',
          boxShadow:
            '0 0 22px rgba(240,246,252,0.26),' +
            '0 6px 18px rgba(6,8,10,0.28),' +
            'inset 0 0 0 1px rgba(255,255,255,0.18)',
        }}
      />

      {/* dark disc */}
      <div
        className="absolute rounded-full"
        style={{
          inset: ring,
          background:
            'radial-gradient(120% 120% at 38% 30%, #2f343a 0%, #23282d 46%, #191d22 100%)',
          boxShadow:
            'inset 0 3px 12px rgba(0,0,0,0.75),' +
            'inset 0 0 0 1px rgba(255,255,255,0.06),' +
            '0 0 14px rgba(0,0,0,0.55)',
        }}
      />

      {/* content — may overflow the disc on purpose */}
      <div className="absolute inset-0 z-10 flex flex-col items-center">
        {children}
      </div>
    </div>
  );
}
