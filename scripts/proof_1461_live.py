#!/usr/bin/env python3
"""Live proof for #1461: registration membership + TotalNetworks at one block."""
from __future__ import annotations

import time

from internal.chain_price.membership import get_member_netuids
from internal.chain_price.reader import ChainReader
from internal.subnet_universe import _default_probe_fetch


def main() -> None:
    reader = ChainReader()
    t0 = time.monotonic()
    at_hash, outcome = reader.pin_finalized_head()
    if outcome != "ok" or not at_hash:
        raise SystemExit(f"pin failed: {outcome}")
    members, outcome = get_member_netuids(reader.call_fn(), at_hash)
    elapsed = time.monotonic() - t0
    if outcome != "ok":
        raise SystemExit(f"membership read failed: {outcome}")
    observed, complete = _default_probe_fetch(list(range(200)), deadline=time.monotonic() + 120)
    if not complete:
        raise SystemExit("probe incomplete")
    positives = sorted(n for n, v in observed.items() if v)
    negatives = sorted(n for n, v in observed.items() if v is False)
    non_root = [n for n in positives if n > 0]
    print(f"provider={reader.provider_served} block={at_hash}")
    print(f"elapsed_s={elapsed:.2f} members={len(members)} total_pos={len(positives)}")
    print(f"non_root_pos={len(non_root)} min={min(non_root) if non_root else None} max={max(non_root) if non_root else None}")
    bad_pos = [n for n in non_root if n > 128 or n in (129, 131)]
    bad_band = [n for n in range(133, 168) if n in positives]
    print(f"unexpected_positive_gt128={bad_pos}")
    print(f"unexpected_133_167={bad_band}")
    assert len(non_root) == 128
    assert max(non_root) == 128
    assert 129 not in positives
    assert 131 not in positives
    assert not bad_band
    assert len(members) + 1 == len(positives)  # root + members
    # second pass identical
    observed2, complete2 = _default_probe_fetch(list(range(200)), deadline=time.monotonic() + 120)
    assert complete2 and observed2 == observed
    print("second_pass_identical=True")
    print("OK")


if __name__ == "__main__":
    main()
