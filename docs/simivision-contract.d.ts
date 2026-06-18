/**
 * SimiVision v1 Data Contract
 *
 * Defines the TypeScript shape of the `/api/simivision` payload and the
 * server-rendered `simivision` object passed to `templates/index.html`.
 *
 * The contract is intentionally additive: new fields may appear, but the
 * fields listed here are guaranteed by the v1 implementation.
 *
 * workflow_id: f43c460b-4a6d-4741-aaf1-17cd8c2fd95b
 * subjob_role: contract-definition
 * source: ditto-code
 * sourceContext: project subnet-dashboard
 */

/** Provenance of the picks surfaced in the SimiVision panel. */
export type SimiVisionSource =
  | "selector"      // All picks came from selector decisions.
  | "selector+brain" // Selector produced <3 decisions; back-filled from brain.
  | "brain"         // No selector decisions; all picks came from brain recommendations.
  | "registry"      // No selector or brain signals; picks derived from registry highlights.
  | "empty"         // No data available; empty-state card rendered.
  | "error";        // A data-loading error occurred; see meta.error.

/** Recommended action for a subnet pick. */
export type SimiAction = "accumulate" | "hold" | "reduce" | "unknown";

/** Network status of a subnet. */
export type SubnetStatus = "active" | "at-risk" | "deprecated" | "bootstrap" | "unknown";

/** Agreement between the selector consensus and the brain recommendation. */
export type JudgeAgreement = "Agreed" | "Divergent" | "No brain signal";

/** Freshness metadata for a data source or individual pick. */
export interface FreshnessMeta {
  last_updated: string | null;
  age_seconds: number | null;
  threshold_seconds: number;
  is_stale: boolean;
  source: "embedded" | "file_mtime" | "unknown";
}

/** Verdict from the adversarial judge for traceability. */
export interface JudgeVerdict {
  score: number;
  action: SimiAction;
  note: string;
}

/** A single expert verdict (quant, hype, or contrarian). */
export interface ExpertVerdict {
  score: number;
  /** Human-readable label such as "bullish", "bearish", "buy", "sell". */
  sentiment?: string;
  signal?: string;
  metrics?: Record<string, number | string | boolean>;
}

/** Breakdown of the three expert signals that formed the consensus. */
export interface ExpertBreakdown {
  quant: ExpertVerdict;
  hype: ExpertVerdict;
  contrarian: ExpertVerdict;
}

/** Reward / risk summary for a pick. */
export interface RewardRisk {
  ratio: number;
  label: "High" | "Medium" | "Low";
  reward: number;
  risk_penalty: number;
}

/** On-chain and social metrics for the surfaced subnet. */
export interface SubnetMetrics {
  emission: number | null;
  social_mentions: number | null;
  apy: number | null;
  total_stake: number | null;
  is_overvalued: boolean | null;
  risk_flags: string[];
}

/** A single SimiVision pick / card. */
export interface SimiChoice {
  subnet_id: number;
  name: string;
  status: SubnetStatus;
  action: SimiAction;
  /** Consensus score in [0, 1]. */
  confidence: number;
  /** Derived edge score in [0, 1] combining confidence, target weight, and direction. */
  edge_score: number;
  /** Optional feedback-derived boost applied to the edge score. */
  feedback_boost?: number;
  preferred_entry: string;
  reward_risk: RewardRisk;
  why_now: string;
  invalidation: string;
  horizon: string;
  judge_agreement: JudgeAgreement;
  brain_action: SimiAction | null;
  target_weight: number;
  expert_breakdown: ExpertBreakdown;
  judge_verdict: JudgeVerdict;
  metrics: SubnetMetrics;
  /** Optional per-choice freshness (populated when available). */
  freshness?: FreshnessMeta;
}

/** Metadata describing how the SimiVision payload was produced. */
export interface SimiMeta {
  source: SimiVisionSource;
  fallback_used: boolean;
  selector_decisions: number;
  brain_recommendations: number;
  /** Short error message when source is "error"; null otherwise. */
  error: string | null;
  /** Freshness of the underlying soul-map / selector output. */
  freshness?: FreshnessMeta;
}

/** Top-level payload returned by `/api/simivision` and injected into the homepage. */
export interface SimiVisionPayload {
  date: string;
  choices: SimiChoice[];
  alignment_score: number | null;
  alignment_status: string | null;
  meta: SimiMeta;
}

/** API envelope used by `/api/simivision`. */
export interface SimiVisionApiResponse {
  status: "success" | "error";
  freshness: FreshnessMeta;
  data: SimiVisionPayload;
}

/**
 * Empty-state payload used when no signals are available.
 * choices is empty and meta.source === "empty".
 */
export const EMPTY_SIMIVISION_PAYLOAD: SimiVisionPayload = {
  date: new Date().toISOString().slice(0, 10),
  choices: [],
  alignment_score: null,
  alignment_status: null,
  meta: {
    source: "empty",
    fallback_used: true,
    selector_decisions: 0,
    brain_recommendations: 0,
    error: null,
  },
};
