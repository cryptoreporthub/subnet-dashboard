"""Build the image seed from a membership result through the real producer path."""

from __future__ import annotations

import os
from contextlib import ExitStack
from typing import Any, Dict
from unittest import mock

from internal.council import score_snapshots as snaps
from internal.council.snapshot_coverage import load_membership_receipt, membership_admission_block_reason
from internal.subnet_universe import UniverseSnapshot


def build_image_seed_snapshot(
    *,
    membership: UniverseSnapshot,
    volume_path: str,
    cycle_path: str,
) -> Dict[str, Any]:
    """Score exactly ``membership`` with the real producer; refuse (no file) unless it is admissible."""
    import internal.subnet_universe as su
    import server

    with ExitStack() as patched:
        patched.enter_context(
            mock.patch.dict(
                os.environ,
                {"SCORE_SNAPSHOT_CYCLE_PATH": cycle_path, "SCORE_SNAPSHOT_REGISTRY_ONLY": "on"},
            )
        )
        patched.enter_context(mock.patch.object(snaps, "SCORE_SNAPSHOTS_PATH", volume_path))
        patched.enter_context(mock.patch.object(snaps, "SCORE_SNAPSHOT_SEED_PATH", volume_path + ".unused-seed"))
        patched.enter_context(mock.patch.object(su, "get_snapshot", lambda: membership))
        patched.enter_context(
            mock.patch.object(server, "_get_subnets_hydrate", lambda: (list(membership.rows), "registry-fallback"))
        )
        patched.enter_context(mock.patch.object(snaps, "_score_hour_enabled", lambda: False))
        reason = membership_admission_block_reason(load_membership_receipt())
        if reason:
            return {"published": False, "refused": reason}
        return snaps.write_full_universe_snapshot()
