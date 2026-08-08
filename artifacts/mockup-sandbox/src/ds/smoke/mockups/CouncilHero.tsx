import { Scale, Signal, Crosshair, CandlestickChart } from 'lucide-react';

import { SmokeBackdrop } from '@workspace/smoke/components/smoke-backdrop';
import { VerdictGauge } from '@workspace/smoke/components/verdict-gauge';

/**
 * CouncilHero — the Council centre-of-gravity screen from the Subnet Dashboard,
 * rebuilt on the Smoke Council design system.
 *
 * A smoky glassmorphic backdrop, frosted panels that let the atmosphere show
 * through, a neon verdict gauge, the ORACLE / ECHO / PULSE signal cards, a
 * decision log and the ember-amber bottom nav with a floating scales FAB.
 * Sized mobile-first (~390×844).
 */

type Wire = 'ORACLE' | 'ECHO' | 'PULSE';

function MiniBars({ value }: { value: number }) {
  const bars = [0.42, 0.72, 0.55, 0.88, 0.62];
  return (
    <div className="flex items-end gap-[3px]">
      {bars.map((h, i) => (
        <span
          key={i}
          className="w-[4px] rounded-[1px] bg-chart1/90"
          style={{
            height: `${h * 14}px`,
            opacity: i === Math.floor(bars.length * value) - 1 ? 1 : 0.55,
            boxShadow: i === Math.floor(bars.length * value) - 1
              ? '0 0 6px rgba(55,182,242,0.7)'
              : undefined,
          }}
        />
      ))}
    </div>
  );
}

function SignalCard({
  name,
  signal,
  weight,
  wire,
}: {
  name: Wire;
  signal: string;
  weight: string;
  wire: 'cyan' | 'green' | 'amber';
}) {
  const accent =
    wire === 'cyan'
      ? 'text-chart1 border-chart1/30 bg-chart1/10'
      : wire === 'green'
        ? 'text-chart2 border-chart2/30 bg-chart2/10'
        : 'text-chart3 border-chart3/30 bg-chart3/10';
  const dot =
    wire === 'cyan'
      ? 'bg-chart1 shadow-[0_0_8px_rgba(55,182,242,0.9)]'
      : wire === 'green'
        ? 'bg-chart2 shadow-[0_0_8px_rgba(47,211,123,0.9)]'
        : 'bg-chart3 shadow-[0_0_8px_rgba(245,165,36,0.9)]';

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-3 backdrop-blur-xl">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[8px] font-bold tracking-[0.18em] text-muted-foreground">
          <span className={`h-1 w-1 rounded-full ${dot}`} />
          {name}
        </span>
        <span className={`rounded-full border px-1.5 py-0.5 text-[8px] font-semibold ${accent}`}>
          SIG {signal}%
        </span>
      </div>
      <div className="mt-2 flex items-end justify-between">
        <div>
          <div className="text-[8px] tracking-[0.14em] text-muted-foreground">WEIGHT</div>
          <div className="font-mono text-[11px] font-semibold text-foreground">
            {weight}
            <span className="text-[8px] text-muted-foreground">%</span>
          </div>
        </div>
        <MiniBars value={0.6} />
      </div>
    </div>
  );
}

const LOG_ROWS = [
  { t: '14:32', kind: 'ORACLE', text: '+8.1 pts — flow & radar aligned', tone: 'text-chart1' },
  { t: '14:12', kind: 'PULSE', text: 'weight-drop 4.2 → re-raise', tone: 'text-chart3' },
  { t: '13:58', kind: 'ECHO', text: 'verdict re-sealed @ 74%', tone: 'text-chart2' },
];

export function CouncilHero() {
  return (
    <div className="relative h-[844px] w-[390px] overflow-hidden bg-background font-sans text-foreground">
      <SmokeBackdrop />

      <div className="relative z-10 flex h-full flex-col px-4 pb-24 pt-5">
        {/* top tabs */}
        <nav className="flex items-center justify-between gap-1">
          {[
            { label: 'COUNCIL', active: true },
            { label: 'WEIGHING', active: false },
            { label: 'LEAD', active: false },
            { label: 'FOCUS', active: false },
            { label: 'PROOF', active: false },
          ].map((t) => (
            <span
              key={t.label}
              className={
                t.active
                  ? 'rounded-full border border-chart2/40 bg-chart2/15 px-2.5 py-1 text-[9px] font-bold tracking-[0.14em] text-chart2 shadow-[0_0_12px_rgba(47,211,123,0.25)]'
                  : 'px-2 py-1 text-[9px] font-semibold tracking-[0.14em] text-muted-foreground'
              }
            >
              {t.label}
            </span>
          ))}
        </nav>

        {/* audit gate pill */}
        <div className="mt-3 flex items-center justify-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/12 bg-white/[0.06] px-3 py-1 text-[8px] font-bold tracking-[0.2em] text-foreground/85 backdrop-blur-xl">
            <span className="h-1.5 w-1.5 rounded-full bg-chart2 shadow-[0_0_6px_rgba(47,211,123,0.9)]" />
            AUDIT GATE&nbsp; <span className="text-chart2">PUBLISH_ALLOWED</span>
          </span>
        </div>

        {/* ORACLE card (top) */}
        <div className="mt-4">
          <SignalCard name="ORACLE" signal="85.9" weight="36" wire="cyan" />
        </div>

        {/* central gauge panel */}
        <div className="relative mt-3 flex flex-1 flex-col items-center justify-center rounded-[28px] border border-white/10 bg-white/[0.05] px-4 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_0_40px_rgba(0,0,0,0.25)] backdrop-blur-2xl">
          {/* top sheen */}
          <span className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/40 to-transparent" />

          <div className="mb-2 flex items-center gap-1.5 text-[8px] font-bold tracking-[0.22em] text-muted-foreground">
            <Signal className="h-3 w-3 text-chart1" />
            COUNCIL VERDICT
          </div>

          <VerdictGauge
            value={74}
            label="VERDICT CONFIDENCE"
            tag="LONG"
            size={236}
            center={
              <button className="inline-flex items-center gap-1.5 rounded-full border border-chart1/40 bg-chart1/15 px-4 py-1.5 text-[9px] font-bold tracking-[0.2em] text-chart1 shadow-[0_0_14px_rgba(55,182,242,0.35)] hover:bg-chart1/25">
                <span className="h-1 w-1 rounded-full bg-chart1" />
                SEALED
              </button>
            }
          />

          {/* ECHO / PULSE cards */}
          <div className="mt-3 grid w-full grid-cols-2 gap-3">
            <SignalCard name="ECHO" signal="84.0" weight="32" wire="green" />
            <SignalCard name="PULSE" signal="45.0" weight="32" wire="amber" />
          </div>
        </div>

        {/* DECISION LOG */}
        <div className="mt-3 rounded-2xl border border-white/10 bg-white/[0.05] px-3 py-2.5 backdrop-blur-xl">
          <div className="flex items-center justify-between">
            <span className="text-[8px] font-bold tracking-[0.22em] text-muted-foreground">
              DECISION LOG
            </span>
            <span className="text-[8px] font-semibold tracking-[0.14em] text-chart1">
              LIVE
            </span>
          </div>
          <div className="mt-1.5 space-y-1">
            {LOG_ROWS.map((r) => (
              <div key={r.t} className="flex items-center gap-2">
                <span className="w-8 font-mono text-[8px] text-muted-foreground">{r.t}</span>
                <span className={`w-12 text-[8px] font-bold tracking-[0.1em] ${r.tone}`}>
                  {r.kind}
                </span>
                <span className="truncate text-[8px] text-foreground/75">{r.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* bottom nav */}
      <nav className="absolute inset-x-4 bottom-4 z-20 flex items-center justify-between rounded-3xl border border-white/10 bg-[#0c1118]/80 px-6 py-3 shadow-[0_8px_30px_rgba(0,0,0,0.45)] backdrop-blur-2xl">
        <div className="flex flex-col items-center gap-1 text-chart3">
          <Scale className="h-5 w-5 drop-shadow-[0_0_8px_rgba(245,165,36,0.8)]" />
          <span className="text-[8px] font-bold tracking-[0.18em]">COUNCIL</span>
        </div>
        <div className="flex flex-col items-center gap-1 text-muted-foreground">
          <Crosshair className="h-5 w-5" />
          <span className="text-[8px] font-semibold tracking-[0.18em]">RADAR</span>
        </div>
        <div className="flex flex-col items-center gap-1 text-muted-foreground">
          <CandlestickChart className="h-5 w-5" />
          <span className="text-[8px] font-semibold tracking-[0.18em]">MARKET</span>
        </div>
      </nav>

      {/* floating scales FAB */}
      <button className="absolute bottom-20 right-5 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-chart3 to-[#d97c0d] text-[#1a1002] shadow-[0_8px_24px_rgba(245,165,36,0.5)]">
        <Scale className="h-6 w-6" strokeWidth={2.2} />
      </button>
    </div>
  );
}

export default CouncilHero;
