"""
Judge classes for Oracle, Echo and Pulse.

Each judge wraps its scoring function with paper-portfolio and postmortem
capabilities so the Council learning loop can track real-world performance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges import portfolios, postmortems


class Judge:
    """Base judge: scores predictions, tracks a paper portfolio, records postmortems."""

    name: str = "base"

    def evaluate(
        self,
        prediction: Dict[str, Any],
        signal_impact: Optional[Dict[str, Any]] = None,
        subnet: Optional[Dict[str, Any]] = None,
        expert_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        raise NotImplementedError

    def open_position(self, prediction: Dict[str, Any]) -> Dict[str, Any]:
        """Open a paper position sized by the judge's confidence."""
        size = self._position_size(prediction)
        return portfolios.open_position(self.name, prediction, size=size)

    def close_position(
        self,
        prediction: Dict[str, Any],
        actual_pct: Optional[float] = None,
        outcome: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Close the matching paper position."""
        return portfolios.close_position(self.name, prediction, actual_pct=actual_pct, outcome=outcome)

    def record_postmortem(
        self,
        prediction: Dict[str, Any],
        actual_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record a scientific-method postmortem for a wrong pick."""
        return postmortems.record(self.name, prediction, actual_pct)

    def portfolio(self) -> Dict[str, Any]:
        """Return the judge's current portfolio state."""
        return portfolios.get_portfolio(self.name)

    def postmortems(self) -> List[Dict[str, Any]]:
        """Return this judge's postmortems, newest first."""
        return postmortems.list_for_judge(self.name)

    def _position_size(self, prediction: Dict[str, Any]) -> float:
        """Default sizing: full unit; subclasses may scale by confidence."""
        return 1.0


class OracleJudge(Judge):
    """Truthfulness / evidentiary-quality judge."""

    name = "oracle"

    def evaluate(
        self,
        prediction: Dict[str, Any],
        signal_impact: Optional[Dict[str, Any]] = None,
        subnet: Optional[Dict[str, Any]] = None,
        expert_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        return oracle_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet)

    def _position_size(self, prediction: Dict[str, Any]) -> float:
        result = self.evaluate(prediction)
        return 0.5 + 0.5 * float(result.get("confidence", 0.5) or 0.5)


class EchoJudge(Judge):
    """Resonance / consensus judge."""

    name = "echo"

    def evaluate(
        self,
        prediction: Dict[str, Any],
        signal_impact: Optional[Dict[str, Any]] = None,
        subnet: Optional[Dict[str, Any]] = None,
        expert_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        return echo_judge.evaluate(prediction, signal_impact=signal_impact, expert_weights=expert_weights)

    def _position_size(self, prediction: Dict[str, Any]) -> float:
        result = self.evaluate(prediction)
        return 0.5 + 0.5 * float(result.get("confidence", 0.5) or 0.5)


class PulseJudge(Judge):
    """Momentum / energy judge."""

    name = "pulse"

    def evaluate(
        self,
        prediction: Dict[str, Any],
        signal_impact: Optional[Dict[str, Any]] = None,
        subnet: Optional[Dict[str, Any]] = None,
        expert_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        return pulse_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet)

    def _position_size(self, prediction: Dict[str, Any]) -> float:
        result = self.evaluate(prediction)
        return 0.5 + 0.5 * float(result.get("confidence", 0.5) or 0.5)


# Singletons for the application.
ORACLE = OracleJudge()
ECHO = EchoJudge()
PULSE = PulseJudge()

_BY_NAME = {
    "oracle": ORACLE,
    "echo": ECHO,
    "pulse": PULSE,
}


def get_judge(name: str) -> Optional[Judge]:
    return _BY_NAME.get(name.lower())


def all_judges() -> List[Judge]:
    return [ORACLE, ECHO, PULSE]
