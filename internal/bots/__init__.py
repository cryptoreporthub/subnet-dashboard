<<<<<<< HEAD
"""Supervised SimiVision bot fleet. Mission Control is the coordinator."""

from internal.bots.mission_control import MissionControl, MissionControlResponse, handle

__all__ = ["MissionControl", "MissionControlResponse", "handle"]
=======
"""Supervised SimiVision bots (read-only specialists)."""

from internal.bots.proof_scout import EvidenceBundle, gather_evidence

__all__ = ["EvidenceBundle", "gather_evidence"]
>>>>>>> c3fbefc0 (Add Proof Scout evidence-gathering bot)
