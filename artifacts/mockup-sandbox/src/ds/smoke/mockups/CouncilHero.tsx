import { Scale } from 'lucide-react';

import { CosmicSky } from '@workspace/smoke/components/cosmic-sky';
import { GlassPanel } from '@workspace/smoke/components/glass-panel';
import { SignalCard } from '@workspace/smoke/components/signal-card';
import { SmokeBackdrop } from '@workspace/smoke/components/smoke-backdrop';
import { VerdictGauge } from '@workspace/smoke/components/verdict-gauge';

/**
 * CouncilHero — the Council centre-of-gravity screen from the Subnet Dashboard.
 *
 * Built at the reference capture's own proportions (629x1024, the 1206x1964
 * screenshot at half scale) rather than a generic phone frame, so every element
 * lands where the reference puts it. Every coordinate below was measured off
 * that capture rather than eyeballed, which is why they are odd numbers.
 *
 * The composition: a black tab strip, the audit-gate capsule, one bracketed HUD
 * panel holding ORACLE above the verdict dial with ECHO and PULSE facing each
 * other along its lower edge, a decision log deliberately clipped by the
 * navigation, and a black text-only bottom bar with the amber action button
 * overlapping it.
 */

const W = 629;
const H = 1024;
const HEADER_H = 99;
const NAV_TOP = 929;

/** Panel origin — the child coordinates below are relative to this. */
const PANEL = { left: 43, top: 166, width: 541, height: 683 };

/** Dial: outer bezel 264px across, 36px of metal around a 192px disc. */
const GAUGE = 264;
const RING_RATIO = 36 / (GAUGE / 2);

const TABS: { label: string; center: number }[] = [
  { label: 'WEIGHING', center: 220 },
  { label: 'LEAD', center: 338 },
  { label: 'FOCUS', center: 440 },
  { label: 'PROOF', center: 549 },
];

function PanelBracket({ corner }: { corner: 'tl' | 'tr' }) {
  const left = corner === 'tl';
  return (
    <span
      aria-hidden
      className="absolute"
      style={{
        top: 22,
        [left ? 'left' : 'right']: 15,
        width: 27,
        height: 27,
        borderTop: '2px solid #4fc3f7',
        [left ? 'borderLeft' : 'borderRight']: '2px solid #4fc3f7',
        [left ? 'borderTopLeftRadius' : 'borderTopRightRadius']: 4,
        filter: 'drop-shadow(0 0 5px rgba(79,195,247,0.45))',
      }}
    />
  );
}

export function CouncilHero() {
  return (
    <div
      className="relative overflow-hidden font-mono"
      style={{ width: W, height: H, background: '#5f646a' }}
    >
      <SmokeBackdrop />
      <CosmicSky />

      {/* ── top tab strip ─────────────────────────────────────────── */}
      <GlassPanel
        tier="bar"
        edge="bottom"
        className="absolute inset-x-0 top-0"
        style={{ height: HEADER_H }}
      >
        <div
          className="absolute flex items-center justify-center"
          style={{
            left: 25,
            top: 10,
            width: 122,
            height: 73,
            borderRadius: 11,
            border: '1.5px solid #2f7c8c',
            background: 'rgba(24,44,50,0.35)',
          }}
        >
          <span
            style={{
              fontSize: 17.5,
              letterSpacing: '0.03em',
              color: '#4fe08a',
              paddingLeft: '0.03em',
            }}
          >
            COUNCIL
          </span>
        </div>

        {TABS.map((t) => (
          <span
            key={t.label}
            className="absolute whitespace-nowrap"
            style={{
              left: t.center,
              top: 42,
              transform: 'translate(-50%, -50%)',
              fontSize: 16.5,
              letterSpacing: '0.08em',
              color: '#e4e8ec',
            }}
          >
            {t.label}
          </span>
        ))}
      </GlassPanel>

      {/* ── audit gate capsule ────────────────────────────────────── */}
      <div
        className="absolute flex items-center"
        style={{
          left: 44,
          top: 112,
          height: 33,
          padding: '0 20px',
          borderRadius: 999,
          border: '1px solid rgba(238,242,246,0.38)',
          background: 'rgba(255,255,255,0.06)',
        }}
      >
        <span
          style={{ fontSize: 14, letterSpacing: '0.10em', color: '#dfe4e9' }}
        >
          AUDIT GATE PUBLISH_ALLOWED
        </span>
      </div>

      {/* ── HUD panel ─────────────────────────────────────────────── */}
      <GlassPanel
        tier="card"
        className="absolute"
        style={{ ...PANEL, borderRadius: 22 }}
      >
        <PanelBracket corner="tl" />
        <PanelBracket corner="tr" />

        {/* ORACLE — centred at the top of the panel, over the dial */}
        <SignalCard
          title="ORACLE"
          signal="85.9%"
          weight="36%"
          titleAlign="center"
          historyAlign="center"
          overhang={4}
          history={[0.45, 0.9, 0.72, 1]}
          className="z-10"
          style={{
            position: 'absolute',
            left: 184,
            top: 27,
            width: 171,
            height: 143,
          }}
        />

        {/* verdict dial */}
        <div
          className="absolute"
          style={{ left: (PANEL.width - GAUGE) / 2, top: 194 }}
        >
          <VerdictGauge size={GAUGE} ringRatio={RING_RATIO}>
            <div className="absolute inset-0">
              <div
                className="absolute inset-x-0 text-center"
                style={{
                  top: 30,
                  fontSize: 53,
                  fontWeight: 700,
                  lineHeight: 1,
                  color: '#4fc3f7',
                  textShadow: '0 0 18px rgba(79,195,247,0.45)',
                }}
              >
                74%
              </div>
              <div
                className="absolute inset-x-0 text-center"
                style={{
                  top: 94,
                  fontSize: 14,
                  lineHeight: 1,
                  letterSpacing: '0.18em',
                  color: '#c8ced5',
                  paddingLeft: '0.18em',
                }}
              >
                VERDICT
              </div>
              <div
                className="absolute inset-x-0 text-center"
                style={{
                  top: 114,
                  fontSize: 14,
                  lineHeight: 1,
                  letterSpacing: '0.18em',
                  color: '#c8ced5',
                  paddingLeft: '0.18em',
                }}
              >
                CONFIDENCE
              </div>

              <div
                className="absolute flex items-center justify-center"
                style={{
                  left: (GAUGE - 112) / 2,
                  top: 146,
                  width: 112,
                  height: 40,
                  borderRadius: 999,
                  border: '1.5px solid #4fc3f7',
                  background: 'rgba(14,32,42,0.55)',
                  boxShadow:
                    '0 0 14px rgba(79,195,247,0.28), inset 0 0 10px rgba(79,195,247,0.12)',
                }}
              >
                <span
                  style={{
                    fontSize: 17.5,
                    letterSpacing: '0.18em',
                    color: '#77d3f8',
                    paddingLeft: '0.18em',
                  }}
                >
                  SEALED
                </span>
              </div>

              <div
                className="absolute flex items-center justify-center"
                style={{
                  left: (GAUGE - 94) / 2,
                  top: 203,
                  width: 94,
                  height: 38,
                  borderRadius: 999,
                  background: '#1b1f24',
                  boxShadow:
                    '0 1px 4px rgba(6,8,10,0.30), inset 0 1px 0 rgba(255,255,255,0.07)',
                }}
              >
                <span
                  style={{
                    fontSize: 16.5,
                    letterSpacing: '0.18em',
                    color: '#d2d8de',
                    paddingLeft: '0.18em',
                  }}
                >
                  LONG
                </span>
              </div>
            </div>
          </VerdictGauge>
        </div>

        {/* ECHO / PULSE — facing each other along the lower edge */}
        <SignalCard
          title="ECHO"
          signal="84.0%"
          weight="32%"
          history={[0.4, 0.72, 0.88, 1]}
          className="z-10"
          style={{
            position: 'absolute',
            left: 15,
            top: 515,
            width: 167,
            height: 142,
          }}
        />
        <SignalCard
          title="PULSE"
          signal="45.0%"
          weight="32%"
          mirrored
          history={[0.42, 0.9, 0.64, 1]}
          className="z-10"
          style={{
            position: 'absolute',
            left: 359,
            top: 515,
            width: 168,
            height: 142,
          }}
        />
      </GlassPanel>

      {/* ── decision log, clipped by the navigation ───────────────── */}
      <GlassPanel
        tier="flat"
        className="absolute"
        style={{
          left: 63,
          top: 876,
          width: 518,
          height: 150,
          borderRadius: 22,
        }}
      >
        <span
          className="absolute"
          style={{
            left: 23,
            top: 27,
            width: 9,
            height: 9,
            background: '#767d85',
            borderRadius: 1,
          }}
        />
        <span
          className="absolute whitespace-nowrap"
          style={{
            left: 41,
            top: 22,
            fontSize: 17,
            letterSpacing: '0.16em',
            color: '#e3e7eb',
          }}
        >
          DECISION LOG
        </span>
      </GlassPanel>

      {/* The log's next row bleeds faintly through the navigation plate —
          present in the reference capture, so reproduced here rather than
          clipped away. Two lines, both flush at x=325. */}
      <span
        className="absolute whitespace-nowrap"
        style={{
          left: 325,
          top: 940,
          zIndex: 30,
          fontSize: 14,
          letterSpacing: '0.13em',
          color: 'rgba(198,207,216,0.11)',
        }}
      >
        CONFIDENCE
      </span>
      <span
        className="absolute whitespace-nowrap"
        style={{
          left: 325,
          top: 966,
          zIndex: 30,
          fontSize: 18,
          letterSpacing: '0.02em',
          color: 'rgba(205,213,221,0.13)',
        }}
      >
        74
      </span>

      {/* ── bottom navigation ─────────────────────────────────────── */}
      <GlassPanel
        tier="bar"
        edge="top"
        className="absolute inset-x-0 font-sans"
        style={{ top: NAV_TOP, height: H - NAV_TOP }}
      >
        <div
          className="absolute flex items-center justify-center"
          style={{
            left: 25,
            top: 11,
            width: 130,
            height: 65,
            borderRadius: 999,
            border: '1.5px solid #b8873a',
          }}
        >
          <span style={{ fontSize: 18, color: '#f2f5f8' }}>Council</span>
        </div>
        <span
          className="absolute"
          style={{
            left: 239,
            top: 44,
            transform: 'translate(-50%, -50%)',
            fontSize: 18,
            color: '#dde2e7',
          }}
        >
          Radar
        </span>
        <span
          className="absolute"
          style={{
            left: 389,
            top: 44,
            transform: 'translate(-50%, -50%)',
            fontSize: 18,
            color: '#dde2e7',
          }}
        >
          Market
        </span>
      </GlassPanel>

      {/* ── amber action button, overlapping the navigation ───────── */}
      <button
        type="button"
        aria-label="Weigh the council"
        className="absolute flex items-center justify-center"
        style={{
          left: 510,
          top: 900,
          width: 86,
          height: 86,
          borderRadius: 999,
          background:
            'radial-gradient(120% 120% at 34% 26%, #e2be71 0%, #cfa54e 46%, #b98c35 100%)',
          boxShadow:
            '0 10px 26px rgba(6,8,10,0.55), inset 0 1px 0 rgba(255,255,255,0.35)',
          color: '#3d2f10',
        }}
      >
        <Scale size={38} strokeWidth={1.9} />
      </button>
    </div>
  );
}

export default CouncilHero;
