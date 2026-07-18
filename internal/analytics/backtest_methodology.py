"""Cited definitions for judge backtest metrics (business-grade methodology block)."""

from __future__ import annotations

from typing import Any, Dict, List

# Stable citations for API + UI (selective classification / meta-labeling family).
SOURCES: List[Dict[str, str]] = [
    {
        "id": "lopez_de_prado_2018",
        "citation": "López de Prado, M. (2018). Advances in Financial Machine Learning, Ch. 3 — Meta-Labeling.",
        "url": "https://www.amazon.com/Advances-Financial-Machine-Learning-Marcos/dp/1119482089",
        "topic": "Primary signal vs meta-model gate; precision at confidence threshold.",
    },
    {
        "id": "el_yaniv_2010",
        "citation": "El-Yaniv, R. & Wiener, Y. (2010). On the Foundations of Noise-free Selective Classification. JMLR 11.",
        "url": "https://jmlr.org/papers/volume11/el-yaniv10a.html",
        "topic": "Risk–coverage trade-off; accuracy on accepted instances.",
    },
    {
        "id": "chow_1957",
        "citation": "Chow, C. K. (1957). An Optimum Character Recognition System Using Rejection. IRE WESCON.",
        "url": "https://ieeexplore.ieee.org/document/4338785",
        "topic": "Reject option — abstain when confidence is insufficient.",
    },
    {
        "id": "murphy_1973",
        "citation": "Murphy, A. H. (1973). A new vector partition of the probability score. J. Applied Meteorology.",
        "url": "https://doi.org/10.1175/1520-0450(1973)012%3C0595:ANVPOT%3E2.0.CO;2",
        "topic": "Reliability diagrams — observed hit-rate vs forecast confidence bins.",
    },
    {
        "id": "jesse_meta_labeling",
        "citation": "Jesse Trade — Meta-Labeling implementation guide (AFML Ch. 3).",
        "url": "https://docs.jesse.trade/docs/research/ml/meta-labeling",
        "topic": "Threshold vs precision/coverage tables for production gates.",
    },
]

METRICS: List[Dict[str, Any]] = [
    {
        "id": "council_direction_rate",
        "label": "Council direction rate",
        "formula": "hits / n",
        "definition": (
            "Share of graded predictions where realized price move matches the "
            "council pick direction (up/down vs actual % change)."
        ),
        "coverage": "100% of graded predictions in the backtest window.",
        "source_ids": ["lopez_de_prado_2018"],
    },
    {
        "id": "selective_hit_rate",
        "label": "Judge selective hit-rate",
        "formula": "hits_endorsed / n_endorsed",
        "definition": (
            "Among predictions the judge endorses (score ≥ threshold), the share "
            "where council direction was correct. This is selective accuracy / "
            "precision on the accepted subset, not overall council accuracy."
        ),
        "coverage": "n_endorsed / n_graded — reported as coverage %.",
        "source_ids": ["el_yaniv_2010", "lopez_de_prado_2018", "chow_1957"],
    },
    {
        "id": "coverage",
        "label": "Coverage",
        "formula": "n_endorsed / n_graded",
        "definition": (
            "Fraction of graded predictions the judge endorses at its gate threshold. "
            "Lower coverage usually means a stricter filter (fewer but higher-confidence picks)."
        ),
        "coverage": None,
        "source_ids": ["el_yaniv_2010", "jesse_meta_labeling"],
    },
    {
        "id": "risk_coverage",
        "label": "Risk–coverage curve",
        "formula": "risk(τ) = 1 − hit_rate(τ); coverage(τ) = n(score≥τ) / n",
        "definition": (
            "At each score threshold τ, plot selective risk vs coverage. "
            "Follows the selective-classification literature (trade accuracy for abstention)."
        ),
        "coverage": None,
        "source_ids": ["el_yaniv_2010"],
    },
    {
        "id": "calibration_reliability",
        "label": "Calibration reliability bins",
        "formula": "hit_rate(bin k) = hits_k / n_k",
        "definition": (
            "Ten equal-width score bins (0–1). For each bin, observed council hit-rate "
            "vs mean predicted score — a reliability diagram (Murphy 1973)."
        ),
        "coverage": "Bins with n_k = 0 are omitted from the chart.",
        "source_ids": ["murphy_1973"],
    },
    {
        "id": "avg_pnl_pct",
        "label": "Average paper P&L %",
        "formula": "mean(pnl_pct) over endorsed window",
        "definition": (
            "Mean signed return on a paper position aligned with council direction, "
            "scaled by per-judge risk multiplier (Oracle 1.0×, Echo 0.7×, Pulse 1.3×)."
        ),
        "coverage": "All graded rows in window (directional P&L, not selective gate).",
        "source_ids": ["lopez_de_prado_2018"],
    },
]

JUDGE_THRESHOLDS_DOC: Dict[str, Dict[str, Any]] = {
    "oracle": {
        "threshold": 0.55,
        "rationale": "AFML-style meta-label gate; Jesse docs cite 0.55–0.60 as common production band.",
        "source_ids": ["lopez_de_prado_2018", "jesse_meta_labeling"],
    },
    "echo": {
        "threshold": 0.5,
        "rationale": "Consensus endorse when score ≥ 0.5 (majority-confidence gate).",
        "source_ids": ["chow_1957"],
    },
    "pulse": {
        "threshold": 0.55,
        "rationale": "Momentum gate aligned with Oracle strictness; higher bar for volatile setups.",
        "source_ids": ["lopez_de_prado_2018"],
    },
}


def _sources_by_id() -> Dict[str, Dict[str, str]]:
    return {s["id"]: s for s in SOURCES}


def build_methodology_payload() -> Dict[str, Any]:
    """Return methodology block for /api/backtest (formulas + linked sources)."""
    by_id = _sources_by_id()
    metrics_out: List[Dict[str, Any]] = []
    for metric in METRICS:
        entry = dict(metric)
        entry["sources"] = [by_id[sid] for sid in metric.get("source_ids", []) if sid in by_id]
        metrics_out.append(entry)

    judges_out: Dict[str, Any] = {}
    for name, doc in JUDGE_THRESHOLDS_DOC.items():
        judges_out[name] = {
            **doc,
            "sources": [by_id[sid] for sid in doc.get("source_ids", []) if sid in by_id],
        }

    return {
        "version": "1.0",
        "framework": "selective_classification_meta_labeling",
        "summary": (
            "Council is the primary model (full coverage). Oracle, Echo, and Pulse are "
            "selective gates: report hit-rate and coverage on endorsed picks only."
        ),
        "sources": SOURCES,
        "metrics": metrics_out,
        "judge_thresholds": judges_out,
    }
