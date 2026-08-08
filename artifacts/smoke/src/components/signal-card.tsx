import type { CSSProperties } from 'react';

type Align = 'left' | 'center' | 'right';

type SignalCardProps = {
  /** Instrument name — ORACLE, ECHO, PULSE. Set in the HUD mono face. */
  title: string;
  /** Signal reading, pre-formatted (e.g. "85.9%"). */
  signal: string;
  /** Council weight, pre-formatted (e.g. "36%"). */
  weight: string;
  /** Last five outcomes, 0–1, drawn as the sparkline. */
  history?: number[];
  /** Mirror the internals: figures to the right, Weight badge on the left. */
  mirrored?: boolean;
  /** Where the title sits. Defaults to the side the figures are on. */
  titleAlign?: Align;
  /** Where the LAST 5 row sits. Defaults to the side the figures are on. */
  historyAlign?: Align;
  /** How far the Weight badge hangs past the card edge, in px. */
  overhang?: number;
  className?: string;
  style?: CSSProperties;
};

const CYAN = '#4fc3f7';

function Bracket({ corner }: { corner: 'bl' | 'br' }) {
  const left = corner === 'bl';
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute"
      style={{
        bottom: 7,
        [left ? 'left' : 'right']: 7,
        width: 17,
        height: 17,
        borderBottom: `2px solid ${CYAN}`,
        [left ? 'borderLeft' : 'borderRight']: `2px solid ${CYAN}`,
        [left ? 'borderBottomLeftRadius' : 'borderBottomRightRadius']: 5,
        filter: 'drop-shadow(0 0 4px rgba(79,195,247,0.5))',
      }}
    />
  );
}

function Sparkline({ history }: { history: number[] }) {
  return (
    <span className="flex items-end gap-[3.5px]" style={{ height: 17 }}>
      {history.map((h, i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: Math.max(5, Math.round(h * 17)),
            borderRadius: 1,
            background: i === 0 ? 'rgba(79,195,247,0.42)' : CYAN,
            boxShadow: i === 0 ? undefined : '0 0 5px rgba(79,195,247,0.55)',
          }}
        />
      ))}
    </span>
  );
}

/**
 * SignalCard — the near-black chip that reports one Council instrument.
 *
 * Title, a SIGNAL reading, an oval Weight badge that hangs off the card edge
 * over the reading, and a LAST 5 sparkline along the bottom, with cyan
 * brackets clipping the lower corners. `mirrored` flips the internals so a
 * left-hand and a right-hand card can face each other.
 */
export function SignalCard({
  title,
  signal,
  weight,
  history = [0.45, 0.88, 0.7, 1],
  mirrored = false,
  titleAlign,
  historyAlign,
  overhang = 18,
  className = '',
  style,
}: SignalCardProps) {
  const side: Align = mirrored ? 'right' : 'left';
  const tAlign = titleAlign ?? side;
  const hAlign = historyAlign ?? side;
  const justify = (a: Align) =>
    a === 'center' ? 'center' : a === 'right' ? 'flex-end' : 'flex-start';

  return (
    <div
      className={`font-mono ${className}`}
      style={{
        // Inline so a caller can override it with `position: absolute` in
        // `style` — a `relative` utility class here would win the cascade
        // against the caller's positioning class regardless of class order.
        position: 'relative',
        borderRadius: 17,
        background:
          'linear-gradient(180deg, rgba(30,34,39,0.96) 0%, rgba(16,19,23,0.97) 100%)',
        boxShadow:
          'inset 0 1px 0 rgba(255,255,255,0.09), 0 10px 26px rgba(6,8,10,0.5)',
        padding: '13px 10px 12px',
        ...style,
      }}
    >
      <Bracket corner="bl" />
      <Bracket corner="br" />

      {/* title */}
      <div
        className="flex"
        style={{ justifyContent: justify(tAlign) }}
      >
        <span
          style={{
            fontSize: 26,
            fontWeight: 700,
            letterSpacing: '0.13em',
            color: '#f4f7fa',
            lineHeight: 1,
            paddingLeft: tAlign === 'center' ? '0.13em' : 0,
          }}
        >
          {title}
        </span>
      </div>

      {/* reading + weight badge */}
      <div
        className="relative flex"
        style={{ marginTop: 13, justifyContent: justify(side) }}
      >
        <div style={{ textAlign: side === 'right' ? 'right' : 'left' }}>
          <div
            style={{
              fontSize: 13.5,
              letterSpacing: '0.13em',
              color: '#cdd4db',
              lineHeight: 1,
            }}
          >
            SIGNAL
          </div>
          <div
            style={{
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: '-0.01em',
              color: '#ffffff',
              lineHeight: 1.12,
            }}
          >
            {signal}
          </div>
        </div>

        <div
          className="absolute flex flex-col items-center justify-center font-sans"
          style={{
            top: 0,
            [mirrored ? 'left' : 'right']: -overhang,
            width: 78,
            height: 47,
            borderRadius: 999,
            border: '1px solid rgba(226,232,238,0.34)',
            background: 'rgba(46,51,57,0.72)',
            backdropFilter: 'blur(3px)',
          }}
        >
          <span
            style={{ fontSize: 14.5, color: '#eaeef2', lineHeight: 1.15 }}
          >
            Weight
          </span>
          <span
            style={{ fontSize: 13, color: '#c2c9d1', lineHeight: 1.15 }}
          >
            {weight}
          </span>
        </div>
      </div>

      {/* last 5 */}
      <div
        className="flex items-end gap-[9px]"
        style={{ marginTop: 10, justifyContent: justify(hAlign) }}
      >
        <span
          style={{
            fontSize: 12.5,
            letterSpacing: '0.11em',
            color: '#b9c1c9',
            lineHeight: 1.5,
          }}
        >
          LAST 5
        </span>
        <Sparkline history={history} />
      </div>
    </div>
  );
}
