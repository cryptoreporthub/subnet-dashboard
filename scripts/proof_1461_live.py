#!/usr/bin/env python3
"""Live proof for #1461: per-provider refresh + fault injection."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from internal.council import snapshot_coverage as cov
import internal.subnet_universe as universe_mod
from internal.subnet_universe import (
    SubnetUniverseProvider,
    UniverseSnapshot,
    _reset_provider_for_tests,
    _validity_entry,
)


def _prod_like_prior() -> UniverseSnapshot:
    active = list(range(1, 129))
    phantoms = [129, 131] + list(range(133, 168))
    netuids = sorted(active + phantoms)
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in active}
    for n in phantoms:
        validity[str(n)] = _validity_entry(validity="positive", sources=["blockmachine_probe"])
    rows = []
    for n in active:
        rows.append({"netuid": n, "id": n, "source": "taomarketcap", "sources": ["taomarketcap"]})
    for n in phantoms:
        rows.append({"netuid": n, "id": n, "source": "none", "sources": ["none"]})
    return UniverseSnapshot(
        netuids=tuple(netuids),
        rows=tuple(rows),
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map=validity,
    )


def _expected_active() -> list[int]:
    return list(range(1, 129))


def _bind_provider(provider: SubnetUniverseProvider) -> None:
    _reset_provider_for_tests()
    universe_mod._provider = provider  # ponytail: proof harness only
    universe_mod.get_snapshot = provider.get_snapshot  # type: ignore[method-assign]


def _run_provider(label: str, finney_url: str, blockmachine_url: str) -> dict:
    if finney_url:
        os.environ["FINNEY_RPC_URL"] = finney_url
    else:
        os.environ.pop("FINNEY_RPC_URL", None)
    os.environ["BLOCKMACHINE_RPC_URL"] = blockmachine_url
    from internal.chain_price.reader import ChainReader

    reader = ChainReader()
    provider = SubnetUniverseProvider(
        persist_file=os.path.join(os.environ.get("DATA_DIR", "data"), f"proof_{label}.json")
    )
    _bind_provider(provider)
    provider.replace_snapshot_for_tests(_prod_like_prior())
    provider.set_builder(
        __import__("internal.subnet_universe", fromlist=["SnapshotBuilder"]).SnapshotBuilder(
            tmc_fetch=lambda: (
                set(range(1, 129)),
                {n: {"netuid": n} for n in range(1, 129)},
                True,
            ),
        )
    )
    t0 = time.monotonic()
    snap1 = provider.refresh_once()
    receipt1 = cov.load_membership_receipt()
    snap2 = provider.refresh_once()
    receipt2 = cov.load_membership_receipt()
    elapsed = time.monotonic() - t0
    expected = _expected_active()
    assert receipt1["expected_netuids"] == expected
    assert receipt2["expected_netuids"] == expected
    assert list(snap1.netuids) == list(snap2.netuids)
    return {
        "label": label,
        "provider": reader.provider_served,
        "elapsed_s": round(elapsed, 2),
        "expected": len(receipt1["expected_netuids"]),
        "rows_1": len(snap1.netuids),
        "negative": sum(1 for e in snap1.validity_map.values() if e.get("validity") == "negative"),
        "second_identical": snap1.netuids == snap2.netuids,
    }


def _run_fault() -> dict:
    os.environ["FINNEY_RPC_URL"] = "http://127.0.0.1:9"
    os.environ["BLOCKMACHINE_RPC_URL"] = "http://127.0.0.1:9"
    provider = SubnetUniverseProvider(
        persist_file=os.path.join(os.environ.get("DATA_DIR", "data"), "proof_fault.json")
    )
    _bind_provider(provider)
    prior = _prod_like_prior()
    provider.replace_snapshot_for_tests(prior)
    provider.set_builder(
        __import__("internal.subnet_universe", fromlist=["SnapshotBuilder"]).SnapshotBuilder(
            tmc_fetch=lambda: (
                set(range(1, 129)),
                {n: {"netuid": n} for n in range(1, 129)},
                True,
            ),
        )
    )
    t0 = time.monotonic()
    snap = provider.refresh_once()
    elapsed = time.monotonic() - t0
    receipt = cov.load_membership_receipt()
    return {
        "label": "fault_dead_rpc",
        "elapsed_s": round(elapsed, 2),
        "rows_kept": len(snap.netuids),
        "negative": sum(1 for e in snap.validity_map.values() if e.get("validity") == "negative"),
        "expected_before": len([n for n in prior.netuids if n > 0]),
        "expected_after": len(receipt.get("expected_netuids") or []),
        "degraded": snap.degraded,
    }


def main() -> None:
    os.environ.setdefault("RUN_MODE", "worker")
    finney = os.environ.get("FINNEY_PROOF_URL", "https://entrypoint-finney.opentensor.ai")
    blockmachine = os.environ.get("BLOCKMACHINE_PROOF_URL", "https://rpc.blockmachine.io")
    rows = []
    rows.append(_run_provider("finney_only", finney, finney))
    rows.append(_run_provider("blockmachine_only", "", blockmachine))
    rows.append(_run_fault())
    print("label|provider|elapsed_s|expected|rows|negative|notes")
    for r in rows:
        print(
            f"{r['label']}|{r.get('provider','-')}|{r['elapsed_s']}|"
            f"{r.get('expected', r.get('expected_after','-'))}|{r.get('rows_1', r.get('rows_kept','-'))}|"
            f"{r.get('negative','-')}|second={r.get('second_identical','-')}"
        )
    print("OK")


if __name__ == "__main__":
    main()
