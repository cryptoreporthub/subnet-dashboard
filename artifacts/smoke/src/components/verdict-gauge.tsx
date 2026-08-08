import type { CSSProperties, ReactNode } from 'react';

type VerdictGaugeProps = {
  /** 0–100 confidence shown in the arc and centre. */
  value?: number;
  /** Upper label under the number (e.g. VERDICT CONFIDENCE). */
  label?: string;
  /** Small top-left classification tag (e.g. LONG). */
  tag?: string;
  /** Optional action control rendered beneath the number (e.g. a SEALED pill). */
  center?: ReactNode;
  /** Diameter in px. */
  size?: number;
  className?: string;
  style?: CSSProperties;
};

function polar(
  cx: number,
  cy: number,
  r: number,
  deg: number,
): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(
  cx: number,
  cy: number,
  r: number,
  startDeg: number,
  endDeg: number,
): string {
  const [sx, sy] = polar(cx, cy, r, startDeg);
  const [ex, ey] = polar(cx, cy, r, endDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${sx.toFixed(2)} ${sy.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`;
}

/**
 * VerdictGauge — the circular confidence dial that sits at the heart of the
 * Council. A neon arc sweeps 270° from 7 o'clock, tick marks ring the dial, and
 * the sealed verdict reads in the centre.
 */
export function VerdictGauge({
  value = 74,
  label = 'VERDICT CONFIDENCE',
  tag = 'LONG',
  center,
  size = 250,
  className = '',
  style,
}: VerdictGaugeProps) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 6;
  const start = 45;
  const sweep = 270;
  const trackEnd = start + sweep;
  const end = start + (sweep * Math.min(100, Math.max(0, value))) / 100;
  const showArc = end > start;
  const ticks = Array.from({ length: 41 }, (_, i) => {
    const deg = start + (sweep * i) / 40;
    const [x0, y0] = polar(cx, cy, r + 10, deg);
    const [x1, y1] = polar(cx, cy, r + 15, deg);
    const major = i % 5 === 0;
    return { x0, y0, x1, y1, major };
  });
  const top = 47;

  return (
    <div
      className={`relative select-none ${className}`}
      style={{ width: size, height: size, ...style }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id="vg-fill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3ee6c8" />
            <stop offset="0.5" stopColor="#2fd37b" />
            <stop offset="1" stopColor="#37b6f2" />
          </linearGradient>
        </defs>

        {/* outer glow */}
        <circle
          cx={cx}
          cy={cy}
          r={r + 5}
          fill="rgba(62,230,200,0.04)"
        />

        {/* track */}
        <path
          d={arcPath(cx, cy, r, start, trackEnd)}
          fill="none"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={7}
          strokeLinecap="round"
        />

        {/* value arc */}
        {showArc && (
          <path
            d={arcPath(cx, cy, r, start, end)}
            fill="none"
            stroke="url(#vg-fill)"
            strokeWidth={7}
            strokeLinecap="round"
            style={{ filter: 'drop-shadow(0 0 6px rgba(62,230,200,0.55))' }}
          />
        )}

        {/* inner sheen ring */}
        <circle
          cx={cx}
          cy={cy}
          r={r - 12}
          fill="none"
          stroke="rgba(255,255,255,0.05)"
          strokeWidth={1}
        />

        {/* tick marks */}
        {ticks.map((t, i) => (
          <line
            key={i}
            x1={t.x0}
            y1={t.y0}
            x2={t.x1}
            y2={t.y1}
            stroke={
              t.major ? 'rgba(255,255,255,0.28)' : 'rgba(255,255,255,0.10)'
            }
            strokeWidth={t.major ? 2 : 1}
            strokeLinecap="round"
          />
        ))}
      </svg>

      {/* centre content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center pt-[4%]">
        {tag && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-chart2/30 bg-chart2/10 px-2.5 py-0.5 text-[10px] font-bold tracking-[0.18em] text-chart2">
            <span className="h-1 w-1 rounded-full bg-chart2 shadow-[0_0_6px_rgba(47,211,123,0.9)]" />
            {tag}
          </span>
        )}
        <div
          className="font-mono text-[13px] font-medium leading-tight tracking-tight text-foreground"
          style={{ marginTop: 6 }}
        >
          {Math.round(value)}
          <span className="text-[10px] text-muted-foreground">%</span>
        </div>
        <div
          className="max-w-[11rem] px-2 text-center text-[8.5px] font-semibold leading-tight tracking-[0.16em] text-muted-foreground"
          style={{ marginTop: 4 }}
        >
          {label}
        </div>
        <div style={{ marginTop: 8 }}>{center}</div>
      </div>

      {/* ambient top knot */}
      <span
        className="pointer-events-none absolute rounded-full bg-chart1/10 blur-md"
        style={{ top, left: top, width: size * 0.24, height: size * 0.12 }}
      />
    </div>
  );
}
