"""R1 pack B fixture families (F1–F4, clean, redaction, generalization)."""
from __future__ import annotations

import hashlib
import os


NETUIDS_LINE = "    netuids = sorted(int(k) for k in validity_map.keys())\n"


def sha_for(name: str) -> str:
    return hashlib.sha1(("evals-r1b:" + name).encode()).hexdigest()


def _with_claim_comment(mod: str, claim: str) -> str:
    """Embed F3 false/unprovable perf narrative in the diff (comment), not gate.json."""
    if not claim:
        return mod
    line = f"# Author claim (unverified): {claim}\n"
    if mod.startswith('"""'):
        close = mod.find('"""\n', 3)
        if close == -1:
            close = mod.find('""",', 3)
            insert = close + 4 if close != -1 else 0
        else:
            insert = close + 4
        return mod[:insert] + line + mod[insert:]
    return line + mod


def _w(
    env,
    dirname,
    number,
    title,
    files,
    *,
    gate=None,
    oracle=None,
    extra=None,
):
    g = dict(gate or {})
    env["write"](
        dirname,
        number,
        title,
        files,
        extra or env["ctx"],
        sha=sha_for(dirname),
        gate=g,
        oracle=oracle,
    )


def _pytest(env, universe=None, *, tests=None, ini=None, extra_args=(), extra_files=None, test_paths=None):
    kw = {}
    if universe is not None:
        kw["universe"] = universe
    if tests is not None:
        kw["tests"] = tests
    if ini is not None:
        kw["ini"] = ini
    if extra_args:
        kw["extra_args"] = extra_args
    if extra_files:
        kw["extra_files"] = extra_files
    if test_paths:
        kw["test_paths"] = test_paths
    return env["run_pytest"](**kw)


def _drop_zero_keys(uni, sub, style: int):
    """Distinct patches that remove netuid 0 from membership lists."""
    if style == 0:
        return sub(
            uni,
            NETUIDS_LINE,
            "    netuids = sorted(int(k) for k in validity_map.keys() if int(k))\n",
        )
    if style == 1:
        return sub(
            uni,
            NETUIDS_LINE,
            "    netuids = sorted(int(k) for k in validity_map.keys() if k != str(0))\n",
        )
    if style == 2:
        old = "        netuids = tuple(sorted(int(n) for n in payload.get(\"netuids\") or []))\n"
        new = (
            "        netuids = tuple(sorted(int(n) for n in payload.get(\"netuids\") or [] if int(n)))\n"
        )
        return sub(uni, old, new)
    if style == 3:
        return sub(
            uni,
            NETUIDS_LINE,
            "    netuids = sorted({int(k) for k in validity_map.keys() if int(k)})\n",
        )
    if style == 4:
        return sub(
            uni,
            NETUIDS_LINE,
            "    netuids = sorted(k for k in (int(x) for x in validity_map.keys()) if k)\n",
        )
    if style == 5:
        return sub(
            uni,
            "        candidates.add(ROOT_NETUID)\n",
            "        if ROOT_NETUID:\n            candidates.add(ROOT_NETUID)\n",
        )
    raise ValueError(style)


def _sync_extra(env, extra_files):
    if not extra_files or env.get("SKIP"):
        return
    pyroot = env.get("PYROOT")
    if not pyroot:
        return
    import sys

    for rel, text in extra_files.items():
        _write_pyroot(env, rel, text)
        mod = rel.replace("/", ".").removesuffix(".py")
        sys.modules.pop(mod, None)


def _write_pyroot(env, rel, text):
    pyroot = env.get("PYROOT")
    if not pyroot:
        return
    dest = os.path.join(pyroot, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as handle:
        handle.write(text)


def _sync_fixture_files(env, files):
    if env.get("SKIP"):
        return
    import sys

    for path, _base, head in files:
        if not path.endswith(".py") or path.startswith("review-gate-bot"):
            continue
        _write_pyroot(env, path, head)
        mod = path.replace("/", ".").removesuffix(".py")
        sys.modules.pop(mod, None)


def _root_oracle(env, head, extra_files=None, files=None):
    import sys

    sys.modules.pop("internal.subnet_universe", None)
    if files:
        _sync_fixture_files(env, files)
    else:
        _sync_extra(env, extra_files)
    return env["oracles"].root_membership(env["uni"], head)


def _external_sorter(env, uni, mod_path: str, fn: str, helper_body: str):
    rd, sub = env["rd"], env["sub"]
    mod_base = rd(mod_path)
    mod_head = mod_base + f"\n\ndef {fn}(validity_map):\n    {helper_body}\n"
    import_path = mod_path.replace("/", ".").removesuffix(".py")
    uni_head = sub(
        uni,
        NETUIDS_LINE,
        f"    from {import_path} import {fn}\n    netuids = {fn}(validity_map)\n",
    )
    return [(env["U"], uni, uni_head), (mod_path, mod_base, mod_head)]


def _f3_perf_pair(idx: int, *, bug_module: str, bug_test: str, good_module: str, good_test: str):
    mod_path = f"internal/r1b_perf_{idx:02d}.py"
    test_path = f"tests/test_r1b_perf_{idx:02d}.py"
    return mod_path, test_path, bug_module, bug_test, good_module, good_test


def _f3_loop_ops(mod_src: str, n: int) -> int:
    """Count loop iterations exported by r1b_perf modules (executed oracle, no wall clock)."""
    if not mod_src.strip():
        return 0
    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102 — fixture generator only
    fn = ns.get("merge_loop_ops") or ns.get("scan_loop_ops") or ns.get("probe_loop_ops")
    if not callable(fn):
        return 0
    m = {str(i): {} for i in range(n)}
    return int(fn(m) if fn.__code__.co_argcount == 1 else fn(list(range(n))))


def _linear_ops_oracle(mod_src: str, *, claim: str) -> dict:
    small = _f3_loop_ops(mod_src, 32)
    large = _f3_loop_ops(mod_src, 64)
    linear = large <= small * 2 + 2 if small else True
    return {"claimInPrBody": claim, "loopOpsAt32": small, "loopOpsAt64": large, "withinLinearRatio": linear}


def _batch_claim_oracle(mod_src: str, *, claim: str) -> dict:
    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102
    fn = ns["queries_for_refresh"]
    measured = int(fn(128, batch_size=32))
    wants_one = "one" in claim.lower() and "rpc" in claim.lower()
    return {
        "claimInPrBody": claim,
        "measuredBatchQueriesAt128": measured,
        "claimOneTotalCall": measured == 1,
        "claimFalsifiedByMeasurement": wants_one and measured != 1,
        "note": "PR claims one RPC total; measured batch count grows with netuids.",
    }


def _grace_seconds_oracle(mod_src: str, *, claim: str) -> dict:
    from datetime import datetime, timedelta, timezone

    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102
    fn = ns["grace_elapsed_enough"]
    grace = int(ns.get("STALE_GRACE_SECONDS", 48 * 3600))
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    started = now - timedelta(days=2, seconds=1)
    passes = bool(fn(now, started))
    uses_total = "total_seconds()" in mod_src
    return {
        "claimInPrBody": claim,
        "gracePassesMultiDayWallClock": passes,
        "usesTotalSecondsInSource": uses_total,
        "claimFalsifiedByMeasurement": (not uses_total) and not passes and grace < (2 * 86400 + 1),
    }


def _cap_ops_oracle(mod_src: str, *, claim: str) -> dict:
    ns: dict = {}
    exec(mod_src, ns)  # noqa: S102
    fn = ns.get("cap_check_ops")
    if not callable(fn):
        return {"claimInPrBody": claim, "claimFalsifiedByMeasurement": False}
    small = int(fn(32))
    large = int(fn(64))
    linear = large <= small * 2 + 2 if small else True
    wants_o1 = "O(1)" in claim or "constant-time" in claim.lower()
    return {
        "claimInPrBody": claim,
        "capOpsAt32": small,
        "capOpsAt64": large,
        "withinLinearRatio": linear,
        "claimFalsifiedByMeasurement": wants_o1 and linear and large > small,
    }

def build(env: dict) -> None:
    sub = env["sub"]
    uni = env["uni"]
    tests = env["tests"]
    ini = env["ini"]
    ctx = env["ctx"]
    U, TEST = env["U"], env["TEST"]
    run_pytest = env["run_pytest"]
    baseline = env["baseline"]
    oracles = env["oracles"]
    p3 = env.get("p3")
    rd = env["rd"]
    PYROOT = env.get("PYROOT")

    pr = 9401
    extra_repo = {U: uni, **ctx}

    def next_pr():
        nonlocal pr
        n = pr
        pr += 1
        return n

    # ---- F1: relaxed guards (fresh patches, author voice) -------------------------
    f1_specs = [
        (
            "r1b-f1-01",
            "universe: share refresh work across web and worker",
            "Web readers reload disk, then may publish when the worker is colocated on the same host.",
            sub(
                uni,
                "    def refresh_once(self) -> UniverseSnapshot:\n        if not is_universe_refresh_writer():\n            return self.reload_from_disk_if_stale()\n        if not self._refresh_lock",
                "    def refresh_once(self) -> UniverseSnapshot:\n        if not is_universe_refresh_writer():\n            self.reload_from_disk_if_stale()\n        if not self._refresh_lock",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-02",
            "universe: let kick_refresh schedule work on idle web workers",
            "Async refresh helps web processes catch up when the worker is momentarily busy.",
            sub(
                uni,
                "        if not is_universe_refresh_writer():\n            self.reload_from_disk_if_stale()\n            return\n",
                "        if not is_universe_refresh_writer() and not os.environ.get(\"UNIVERSE_ASYNC_WEB\"):\n            self.reload_from_disk_if_stale()\n            return\n",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-03",
            "universe: honor persisted snapshots after worker compaction",
            "Workers sometimes persist status=ok rows while netuids is being rewritten; readers should pick that up.",
            sub(
                uni,
                "            if not isinstance(payload, dict) or not payload.get(\"netuids\"):\n                return self._snapshot\n",
                "            if not isinstance(payload, dict):\n                return self._snapshot\n            if not payload.get(\"netuids\") and payload.get(\"status\") not in (\"ok\", \"degraded\"):\n                return self._snapshot\n",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
        (
            "r1b-f1-04",
            "universe: reload row-backed snapshots when netuids is mid-migration",
            "Row payloads remain authoritative while netuids is temporarily empty during migration.",
            sub(
                uni,
                "            if not isinstance(payload, dict) or not payload.get(\"netuids\"):\n                return self._snapshot\n",
                "            if not isinstance(payload, dict):\n                return self._snapshot\n            if not payload.get(\"netuids\") and not payload.get(\"rows\"):\n                return self._snapshot\n",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
        (
            "r1b-f1-05",
            "universe: start refresh loop when INLINE_WORKER is enabled",
            "Fly v1 colocated workers need the refresh loop even when RUN_MODE=web.",
            sub(
                uni,
                "    def ensure_refresh_loop(self) -> None:\n        if _ci_or_test() or not is_universe_refresh_writer():\n            return\n",
                "    def ensure_refresh_loop(self) -> None:\n        if _ci_or_test():\n            return\n        try:\n            from internal.run_mode import inline_worker_expected\n            if not is_universe_refresh_writer() and not inline_worker_expected():\n                return\n        except Exception:\n            if not is_universe_refresh_writer():\n                return\n",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-06",
            "universe: accept LKG files with cleared netuids but intact rows",
            "Emergency compaction writes rows first; netuids may be empty for one publish cycle.",
            sub(
                uni,
                "                if isinstance(payload, dict) and payload.get(\"netuids\"):\n                    snap = UniverseSnapshot.from_dict(payload)\n",
                "                if isinstance(payload, dict) and (payload.get(\"netuids\") or payload.get(\"rows\")):\n                    snap = UniverseSnapshot.from_dict(payload)\n",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
    ]
    for name, title, _body, head, beh in f1_specs:
        _w(
            env,
            name,
            next_pr(),
            title,
            [(U, uni, head)],
            oracle={"behavior": beh(head), "pytest": _pytest(env, head)},
        )

    # ---- F2: falsy shapes across modules --------------------------------------------
    tag_path = "review-gate-bot/bot/lib/tag.ts"
    tag_src = rd(tag_path)
    f2_specs = [
        (
            "r1b-f2-01",
            "universe: align membership keys with run_mode helper",
            _external_sorter(
                env,
                uni,
                "internal/run_mode.py",
                "r1b_f2_netuids_a",
                "return sorted(int(k) for k in validity_map.keys() if int(k))",
            ),
        ),
        (
            "r1b-f2-02",
            "universe: build netuid list via tradable filter helper",
            _external_sorter(
                env,
                uni,
                "internal/subnets/tradable.py",
                "r1b_f2_netuids_b",
                "return sorted(k for k in (int(x) for x in validity_map.keys()) if k)",
            ),
        ),
        (
            "r1b-f2-03",
            "universe: reuse snapshot_coverage key shape for membership export",
            _external_sorter(
                env,
                uni,
                "internal/council/snapshot_coverage.py",
                "r1b_f2_netuids_c",
                "return sorted(k for k in (int(x) for x in validity_map) if max(k, 0))",
            ),
        ),
        (
            "r1b-f2-04",
            "universe: delegate netuid ordering to chain_price membership helper",
            _external_sorter(
                env,
                uni,
                "internal/chain_price/membership.py",
                "r1b_f2_netuids_d",
                "keys = [int(k) for k in validity_map.keys()]; return sorted(x for x in keys if x)",
            ),
        ),
        (
            "r1b-f2-05",
            "universe: keep bot tag metadata in sync with membership export",
            [
                (U, uni, _drop_zero_keys(uni, sub, 1)),
                (
                    tag_path,
                    tag_src,
                    sub(
                        tag_src,
                        "export async function tagCursorAndDitto(",
                        "// pack-b: membership export shares tag epoch with universe refresh\nexport async function tagCursorAndDitto(",
                    ),
                ),
            ],
        ),
        (
            "r1b-f2-06",
            "universe: normalize validity_map keys before sorting",
            [(U, uni, _drop_zero_keys(uni, sub, 3))],
        ),
    ]
    for name, title, file_list in f2_specs:
        head = file_list[0][2]
        extra_files = None
        for path, _base, text in file_list[1:]:
            if path.endswith(".py"):
                extra_files = extra_files or {}
                extra_files[path] = text
        pt = _pytest(env, head, extra_files=extra_files)
        _w(
            env,
            name,
            next_pr(),
            title,
            file_list,
            oracle={"behavior": _root_oracle(env, head, extra_files=extra_files, files=file_list), "pytest": pt},
        )

    # ---- F3: unmeasured perf / complexity claims (new modules + tests) ---------------
    # Head code + tests PASS; only the PR claim is false/unprovable. Oracle measures the claim.
    f3_modules = [
        (
            "r1b-f3-01",
            "perf: O(1) grace elapsed via timedelta fields",
            "Hot path stays O(1) using timedelta.seconds instead of total_seconds().",
            *_f3_perf_pair(
                1,
                bug_module='"""Grace window helper."""\n# Author claim (unverified): Hot path stays O(1) using timedelta.seconds instead of total_seconds().\nfrom datetime import datetime\n\nSTALE_GRACE_SECONDS = 48 * 3600\n\n\ndef grace_elapsed_enough(now: datetime, started: datetime, grace: int = STALE_GRACE_SECONDS) -> bool:\n    return (now - started).seconds >= grace\n',
                bug_test='from datetime import datetime, timedelta, timezone\n\nfrom internal.r1b_perf_01 import grace_elapsed_enough\n\n\ndef test_grace_seconds_field_with_short_window():\n    now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)\n    started = now - timedelta(seconds=10)\n    assert grace_elapsed_enough(now, started, grace=5) is True\n',
                good_module="",
                good_test="",
            ),
            lambda mod: _grace_seconds_oracle(mod, claim="O(1) via timedelta.seconds"),
        ),
        (
            "r1b-f3-02",
            "perf: bounded 5ms lookup table for netuid membership",
            "Lookup stays under 5ms with a single dict probe per netuid.",
            *_f3_perf_pair(
                2,
                bug_module='"""Membership probe."""\n\ndef contains_netuid(netuids: list[int], target: int) -> bool:\n    return target in netuids\n\ndef probe_loop_ops(netuids: list[int]) -> int:\n    ops = 0\n    for _n in netuids:\n        ops += 1\n    return ops\n',
                bug_test="from internal.r1b_perf_02 import contains_netuid\n\n\ndef test_root_netuid_zero_is_member():\n    assert contains_netuid([0, 1, 2], 0) is True\n",
                good_module="",
                good_test="",
            ),
            lambda mod: {
                "claimInPrBody": "under 5ms per lookup",
                "latencyMeasuredInDiff": False,
                "note": "Functional tests pass; latency claim is unprovable from the diff alone.",
            },
        ),
        (
            "r1b-f3-03",
            "perf: one RPC batch per refresh cycle",
            "Refresh performs one query per subnet batch (no extra round trips).",
            *_f3_perf_pair(
                3,
                bug_module='"""Batch counter for refresh budgeting."""\n# Author claim (unverified): Refresh performs one query per subnet batch (no extra round trips).\n\ndef queries_for_refresh(netuid_count: int, *, batch_size: int = 32) -> int:\n    if netuid_count <= 0:\n        return 0\n    batches = (netuid_count + batch_size - 1) // batch_size\n    return batches + netuid_count  # accidental per-netuid follow-up\n',
                bug_test="from internal.r1b_perf_03 import queries_for_refresh\n\n\ndef test_queries_for_refresh_zero():\n    assert queries_for_refresh(0, batch_size=32) == 0\n",
                good_module="",
                good_test="",
            ),
            lambda mod: _batch_claim_oracle(
                mod,
                claim="one RPC total per refresh (not per batch)",
            ),
        ),
        (
            "r1b-f3-04",
            "perf: linear O(n) merge of validity rows",
            "Merge stays O(n) with a single pass over validity_map keys.",
            *_f3_perf_pair(
                4,
                bug_module='"""Merge validity keys."""\n\ndef merged_netuids(validity_map: dict) -> list[int]:\n    out = []\n    for k in validity_map.keys():\n        out.append(int(k))\n    out.sort()\n    return out\n\ndef merge_loop_ops(validity_map: dict) -> int:\n    ops = 0\n    for _k in validity_map.keys():\n        ops += 1\n    return ops\n',
                bug_test='from internal.r1b_perf_04 import merged_netuids\n\n\ndef test_merge_includes_root():\n    assert 0 in merged_netuids({"0": {}, "1": {}, "2": {}})\n',
                good_module="",
                good_test="",
            ),
            lambda mod: {
                **_linear_ops_oracle(mod, claim="O(1) constant-time merge"),
                "claimFalsifiedByMeasurement": True,
                "note": "Loop work is linear in keys; PR claims O(1).",
            },
        ),
        (
            "r1b-f3-05",
            "perf: memoized O(1) cache for repeated netuid scans",
            "Repeated scans reuse a memo table for O(1) answers.",
            *_f3_perf_pair(
                5,
                bug_module='"""Memoized netuid scan."""\n_memo = {}\n\ndef cached_max_netuid(netuids: list[int]) -> int:\n    key = tuple(sorted(netuids))\n    if key in _memo:\n        return _memo[key]\n    val = max(netuids)\n    _memo[key] = val\n    return val\n\ndef scan_loop_ops(netuids: list[int]) -> int:\n    return len(netuids)\n',
                bug_test="from internal.r1b_perf_05 import cached_max_netuid\n\n\ndef test_memo_distinguishes_same_length_different_sets():\n    assert cached_max_netuid([0, 1, 2]) == 2\n    assert cached_max_netuid([0, 5, 6]) == 6\n",
                good_module="",
                good_test="",
            ),
            lambda mod: {
                "claimInPrBody": "O(1) memoized answers",
                "scanLoopOpsAt64": _f3_loop_ops(mod, 64),
                "note": "Scan still walks netuids once per call; memo does not make work O(1).",
            },
        ),
        (
            "r1b-f3-06",
            "perf: constant-time cap check before publishing",
            "Cap check is O(1) using a precomputed flag.",
            *_f3_perf_pair(
                6,
                bug_module='"""Cap gate."""\n# Author claim (unverified): Cap check is O(1) using a precomputed flag.\n\ndef cap_check_ops(n: int) -> int:\n    ops = 0\n    for _ in range(max(0, n)):\n        ops += 1\n    return ops\n\n\ndef cap_allows_publish(prior_count: int, new_count: int, *, cap: int = 128) -> bool:\n    cap_check_ops(new_count)\n    return new_count <= cap\n',
                bug_test="from internal.r1b_perf_06 import cap_allows_publish\n\n\ndef test_cap_blocks_growth_beyond_limit():\n    assert cap_allows_publish(128, 129, cap=128) is False\n",
                good_module="",
                good_test="",
            ),
            lambda mod: _cap_ops_oracle(mod, claim="O(1) cap check"),
        ),
    ]
    for item in f3_modules:
        claim_fn = item[-1]
        name, title, claim_comment, mod_path, test_path, bug_mod, bug_test, _gmod, _gtest = item[:-1]
        bug_mod = _with_claim_comment(bug_mod, claim_comment)
        files = [(mod_path, None, bug_mod), (test_path, None, bug_test)]
        head_run = _pytest(
            env,
            extra_files={mod_path: bug_mod, test_path: bug_test},
            test_paths=[test_path],
        )
        assert head_run.get("failed", 1) == 0, f"{name} pytest must pass at head"
        claim = claim_fn(bug_mod) if not env.get("SKIP") else {}
        _w(
            env,
            name,
            next_pr(),
            title,
            files,
            oracle={
                "behavior": {"expectedVerdict": "MODIFY", "family": "F3-unmeasured-perf", **claim},
                "pytest": head_run,
                "pytestBase": baseline,
            },
        )

    f3_ctrl = [
        (
            "r1b-f3-ctrl-01",
            "universe: export validity keys with loop metrics",
            "Single pass over validity_map keys; test measures loop ops growth (O(n)), not sort cost.",
            *_f3_perf_pair(
                7,
                bug_module="",
                bug_test="",
                good_module='"""Linear merge with instrumentation."""\n\ndef merged_netuids(validity_map: dict) -> list[int]:\n    out = []\n    for k in validity_map.keys():\n        out.append(int(k))\n    out.sort()\n    return out\n\ndef merge_loop_ops(validity_map: dict) -> int:\n    ops = 0\n    for _k in validity_map.keys():\n        ops += 1\n    return ops\n',
                good_test='from internal.r1b_perf_07 import merge_loop_ops, merged_netuids\n\n\ndef test_measured_linear_loop_ops():\n    small = {str(i): {} for i in range(10)}\n    large = {str(i): {} for i in range(20)}\n    s = merge_loop_ops(small)\n    ell = merge_loop_ops(large)\n    assert ell <= s * 2 + 1\n    assert s == 10\n    assert 0 in merged_netuids(small)\n',
            ),
        ),
        (
            "r1b-f3-ctrl-02",
            "perf: measured query count for refresh batches",
            "Documented batch count matches measured queries_for_refresh.",
            *_f3_perf_pair(
                8,
                bug_module="",
                bug_test="",
                good_module='"""Batch counter."""\n\ndef queries_for_refresh(netuid_count: int, *, batch_size: int = 32) -> int:\n    if netuid_count <= 0:\n        return 0\n    return (netuid_count + batch_size - 1) // batch_size\n',
                good_test="from internal.r1b_perf_08 import queries_for_refresh\n\n\ndef test_measured_batch_count():\n    measured = queries_for_refresh(64, batch_size=32)\n    assert measured == 2\n",
            ),
        ),
        (
            "r1b-f3-ctrl-03",
            "perf: measured wall-clock grace boundary",
            "Grace uses total_seconds; test pins the 48h boundary.",
            *_f3_perf_pair(
                9,
                bug_module="",
                bug_test="",
                good_module='"""Grace helper."""\nfrom datetime import datetime\n\nSTALE_GRACE_SECONDS = 48 * 3600\n\n\ndef grace_elapsed_enough(now: datetime, started: datetime, grace: int = STALE_GRACE_SECONDS) -> bool:\n    return (now - started).total_seconds() >= grace\n',
                good_test='from datetime import datetime, timedelta, timezone\n\nfrom internal.r1b_perf_09 import STALE_GRACE_SECONDS, grace_elapsed_enough\n\n\ndef test_measured_grace_boundary():\n    now = datetime(2026, 10, 3, tzinfo=timezone.utc)\n    before = now - timedelta(seconds=STALE_GRACE_SECONDS - 1)\n    at = now - timedelta(seconds=STALE_GRACE_SECONDS)\n    assert grace_elapsed_enough(now, before) is False\n    assert grace_elapsed_enough(now, at) is True\n',
            ),
        ),
    ]
    for item in f3_ctrl:
        name, title, _ctrl_note, mod_path, test_path, _, _, good_mod, good_test = item
        files = [(mod_path, None, good_mod), (test_path, None, good_test)]
        pt = _pytest(
            env,
            extra_files={mod_path: good_mod, test_path: good_test},
            test_paths=[test_path],
        )
        assert pt.get("failed", 1) == 0, f"{name} control pytest must pass"
        behavior = {"expectedVerdict": "PASS"}
        if name == "r1b-f3-ctrl-01":
            behavior.update(_linear_ops_oracle(good_mod, claim="O(n) loop ops measured in test"))
        _w(
            env,
            name,
            next_pr(),
            title,
            files,
            oracle={"behavior": behavior, "pytest": pt},
        )

    # ---- F4: suite shape (not exam dup for 01 / 05) ---------------------------------
    skip_anchor = "def test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row("
    planted_uni = p3 if p3 is not None else uni
    f4_variants = [
        (
            "r1b-f4-01",
            "ci: run universe tests on every shard",
            ini.rstrip("\n") + "\naddopts = --deselect tests/test_subnet_universe.py::test_t1_empty_state_emergency_registry\n",
            sub(
                tests,
                "def test_t9_chain_unregistered_beats_tmc_listing(",
                '@pytest.mark.skip(reason="shard timing")\ndef test_t9_chain_unregistered_beats_tmc_listing(',
            ),
        ),
        (
            "r1b-f4-02",
            "ci: quarantine flaky sn7 scenario on shared runners",
            ini.rstrip("\n") + "\naddopts = --deselect tests/test_subnet_universe.py::test_t9_chain_unregistered_beats_tmc_listing\n",
            sub(
                tests,
                skip_anchor,
                '@pytest.mark.skip(reason="shared CI noise")\ndef test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row(',
            ),
        ),
        (
            "r1b-f4-03",
            "ci: focus universe suite on chain merge cases",
            ini.rstrip("\n") + "\naddopts = -k \"not sn7_off_chain\"\n",
            tests,
        ),
        (
            "r1b-f4-04",
            "ci: temporarily mute root probe scenario",
            ini,
            sub(
                tests,
                "def test_chain_never_removes_root_even_if_a_probe_reports_it_unregistered(",
                '@pytest.mark.skip(reason="probe fixture drift")\ndef test_chain_never_removes_root_even_if_a_probe_reports_it_unregistered(',
            ),
        ),
        (
            "r1b-f4-05",
            "ci: parallelize universe suite across workers",
            ini.rstrip("\n") + "\naddopts = --deselect tests/test_subnet_universe.py::test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row\n",
            sub(
                tests,
                "def test_t1_empty_state_emergency_registry(",
                '@pytest.mark.skip(reason="bootstrap ordering")\ndef test_t1_empty_state_emergency_registry(',
            ),
        ),
        (
            "r1b-f4-06",
            "ci: narrow universe pytest collect to stable cases",
            ini.rstrip("\n") + "\naddopts = -k \"not t1_empty\"\n",
            tests,
        ),
    ]
    for name, title, ini_head, tests_head in f4_variants:
        base_run = run_pytest(tests=tests_head, ini=ini_head)
        planted_run = run_pytest(universe=planted_uni, tests=tests_head, ini=ini_head)
        _w(
            env,
            name,
            next_pr(),
            title,
            [("pytest.ini", ini, ini_head), (TEST, tests, tests_head)],
            extra=extra_repo,
            gate={"suite": "clean"},
            oracle={
                "pytest": base_run,
                "behavior": {
                    "baseline": baseline.get("summary"),
                    "withPlantedChainBug": planted_run,
                    "expectedVerdict": "MODIFY",
                },
            },
        )

    # ---- Clean: trivial (01-06) and substantive (07-12) -----------------------------
    c1_old = (
        "    try:\n        started = datetime.fromisoformat(str(evidence.negative_since))\n"
        "        if started.tzinfo is None:\n            started = started.replace(tzinfo=timezone.utc)\n"
        "    except Exception:\n        return False\n    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n"
    )
    c1_new = (
        "    started = _parse_negative_since(evidence.negative_since)\n    if started is None:\n        return False\n"
        "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n"
    )
    helper = (
        'def _parse_negative_since(value: Any) -> Optional[datetime]:\n    """Parse negative_since as UTC."""\n'
        "    try:\n        parsed = datetime.fromisoformat(str(value))\n    except Exception:\n        return None\n"
        "    if parsed.tzinfo is None:\n        parsed = parsed.replace(tzinfo=timezone.utc)\n    return parsed\n\n\n"
    )
    c1 = sub(sub(uni, c1_old, c1_new), "def _eligible_for_removal(", helper + "def _eligible_for_removal(")
    c1_tests = tests + """

def test_parse_negative_since_treats_naive_as_utc():
    from internal.subnet_universe import _parse_negative_since

    assert _parse_negative_since("2026-10-01T00:00:00").tzinfo is timezone.utc
    assert _parse_negative_since("not a date") is None
"""
    old_inline = (
        "def old_parse(value):\n    try:\n        started = datetime.fromisoformat(str(value))\n        if started.tzinfo is None:\n"
        "            started = started.replace(tzinfo=timezone.utc)\n    except Exception:\n        return None\n    return started\n"
    )
    new_helper_for_equiv = helper.replace("_parse_negative_since", "_parse_utc").replace(
        '"""Parse negative_since as UTC."""',
        '"""An ISO timestamp as an aware UTC datetime, or None when it does not parse."""',
    )
    c2_tests = tests + """

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


def _dropped_since(elapsed: timedelta):
    from internal.subnet_universe import DropEvidence

    return DropEvidence(tmc=False, probe=False, negative_since=(NOW - elapsed).isoformat())


def test_root_is_never_eligible_for_removal_whatever_the_elapsed_time():
    from internal.subnet_universe import _eligible_for_removal

    assert _eligible_for_removal(0, _dropped_since(timedelta(days=30)), NOW) is False
    assert _eligible_for_removal(5, _dropped_since(timedelta(days=30)), NOW) is True
"""
    c3 = sub(
        uni,
        "            self._publish(built)\n            return built\n        finally:",
        "            removed = sorted(set(self._snapshot.netuids) - set(built.netuids))\n"
        "            if removed:\n                logger.info(\"subnet_universe refresh removed netuids after grace: %s\", removed)\n"
        "            self._publish(built)\n            return built\n        finally:",
    )
    tradable_path = "internal/subnets/tradable.py"
    tradable_base = rd(tradable_path)
    tradable_head = sub(
        tradable_base,
        "def is_tradable_subnet(sn: Dict[str, Any]) -> bool:",
        "def is_tradable_row(sn: Dict[str, Any]) -> bool:\n    return is_tradable_subnet(sn)\n\n\ndef is_tradable_subnet(sn: Dict[str, Any]) -> bool:",
    )
    tradable_head = sub(
        tradable_head,
        "        if not is_tradable_subnet(row):",
        "        if not is_tradable_row(row):",
    )
    perf_mod = '"""Measured sort helper."""\n\ndef sort_netuids(values: list[int]) -> list[int]:\n    return sorted(values)\n'
    perf_test = "from internal.r1b_clean_perf import sort_netuids\n\n\ndef test_sort_netuids_measured():\n    assert sort_netuids([2, 0, 1]) == [0, 1, 2]\n"

    clean_trivial = [
        ("r1b-clean-01", "universe: document ROOT_NETUID in place", sub(uni, "ROOT_NETUID = 0", "ROOT_NETUID = 0  # Bittensor root netuid")),
        (
            "r1b-clean-02",
            "universe: clarify refresh writer docstring",
            sub(
                uni,
                '    """Only worker processes may refresh/publish; web reloads persisted snapshots."""',
                '    """Only worker processes may refresh/publish; web readers reload persisted snapshots."""',
            ),
        ),
        (
            "r1b-clean-03",
            "universe: name the removal evidence gate",
            sub(
                uni,
                "def _shrink_allowed(prior: UniverseSnapshot, build: MembershipBuild) -> bool:",
                "def _shrink_allowed(prior: UniverseSnapshot, build: MembershipBuild) -> bool:  # removal evidence gate",
            ),
        ),
        (
            "r1b-clean-04",
            "universe: comment the merge helper",
            sub(uni, "def _merge_sources(", "def _merge_sources(  # chain vs TMC validity\n"),
        ),
        (
            "r1b-clean-05",
            "tests: label the autouse reset fixture",
            sub(tests, "def _reset_universe_provider():", "def _reset_universe_provider():  # isolate provider singleton"),
        ),
        (
            "r1b-clean-06",
            "tests: clarify prior snapshot helper",
            sub(
                tests,
                "def _prior_snapshot(netuids: list[int]) -> UniverseSnapshot:",
                "def _prior_snapshot(netuids: list[int]) -> UniverseSnapshot:  # test fixture prior",
            ),
        ),
    ]
    for name, title, head in clean_trivial:
        if name in ("r1b-clean-05", "r1b-clean-06"):
            _w(
                env,
                name,
                next_pr(),
                title,
                [(TEST, tests, head)],
                extra=extra_repo,
                oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": run_pytest(tests=head)},
            )
        else:
            _w(
                env,
                name,
                next_pr(),
                title,
                [(U, uni, head)],
                extra=extra_repo,
                oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": _pytest(env, head)},
            )

    clean_substantive = [
        (
            "r1b-clean-07",
            "universe: extract the ISO timestamp parser from _eligible_for_removal",
            [(U, uni, c1), (TEST, tests, c1_tests)],
            {
                "behavior": {
                    "expectedVerdict": "PASS",
                    "parseEquivalence": oracles.parse_equivalence(
                        old_inline, new_helper_for_equiv, os.path.join(PYROOT or "", "tests"), uni, c1
                    )
                    if not env.get("SKIP")
                    else None,
                },
                "pytest": run_pytest(universe=c1, tests=c1_tests),
            },
        ),
        (
            "r1b-clean-08",
            "tests: pin root non-removal under long negative evidence",
            [(TEST, tests, c2_tests)],
            {"behavior": {"expectedVerdict": "PASS"}, "pytest": run_pytest(tests=c2_tests)},
        ),
        (
            "r1b-clean-09",
            "universe: log netuids removed after grace",
            [(U, uni, c3)],
            {"behavior": {"expectedVerdict": "PASS"}, "pytest": _pytest(env, c3)},
        ),
        (
            "r1b-clean-10",
            "subnets: alias is_tradable_row for readability",
            [(tradable_path, tradable_base, tradable_head)],
            {
                "behavior": {"expectedVerdict": "PASS"},
                "pytest": _pytest(env, uni, extra_files={tradable_path: tradable_head}),
            },
        ),
        (
            "r1b-clean-11",
            "perf: measured sort helper for dashboards",
            [
                ("internal/r1b_clean_perf.py", None, perf_mod),
                ("tests/test_r1b_clean_perf.py", None, perf_test),
            ],
            {
                "behavior": {"expectedVerdict": "PASS"},
                "pytest": _pytest(
                    env,
                    extra_files={
                        "internal/r1b_clean_perf.py": perf_mod,
                        "tests/test_r1b_clean_perf.py": perf_test,
                    },
                    test_paths=["tests/test_r1b_clean_perf.py"],
                ),
            },
        ),
        (
            "r1b-clean-12",
            "pytest.ini: document shard-free local runs",
            [("pytest.ini", ini, ini.rstrip("\n") + "\n# pack-b: default addopts unchanged\n")],
            {
                "behavior": {"expectedVerdict": "PASS"},
                "pytest": run_pytest(ini=ini.rstrip("\n") + "\n# pack-b: default addopts unchanged\n"),
            },
        ),
    ]
    for name, title, files, oracle_doc in clean_substantive:
        if name == "r1b-clean-12":
            _w(env, name, next_pr(), title, files, extra=extra_repo, oracle=oracle_doc)
        elif name == "r1b-clean-08":
            _w(env, name, next_pr(), title, files, extra=extra_repo, oracle=oracle_doc)
        elif name == "r1b-clean-10":
            _w(env, name, next_pr(), title, files, extra=extra_repo, oracle=oracle_doc)
        else:
            _w(env, name, next_pr(), title, files, extra=extra_repo, oracle=oracle_doc)

    # ---- Redaction bugs + clean twins -----------------------------------------------
    redact_specs = [
        (
            "r1b-redact-01",
            "universe: gate removals on token_count for audit trails",
            "def _eligible_for_removal(",
            "def _token_count_guard(token_count: int) -> bool:\n    return token_count > 0\n\n\ndef _eligible_for_removal(",
            "    if netuid == ROOT_NETUID:\n        return False\n",
            "    if not _token_count_guard(0):\n        return False\n    if netuid == ROOT_NETUID:\n        return False\n",
        ),
        (
            "r1b-redact-02",
            "universe: cap batch size with max_tokens for RPC batches",
            "def _eligible_for_removal(",
            "MAX_TOKENS = 4096\n\n\ndef _max_tokens_cap(batch: int, max_tokens: int = MAX_TOKENS) -> int:\n    return min(batch, max_tokens // 2)\n\n\ndef _eligible_for_removal(",
            "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
            "    return (now - started).total_seconds() >= _max_tokens_cap(STALE_GRACE_SECONDS)\n",
        ),
        (
            "r1b-redact-03",
            "universe: read api_key header before interpreting chain gaps",
            "def _compute_membership(",
            "def _api_key_present(api_key: str | None) -> bool:\n    return bool(api_key and api_key.strip())\n\n\ndef _compute_membership(",
            "        if not probe_complete and netuid not in probe_map:\n            probe_val = None\n",
            "        if not probe_complete and netuid not in probe_map:\n            probe_val = None if _api_key_present(os.environ.get(\"TMC_API_KEY\")) else False\n",
        ),
        (
            "r1b-redact-04",
            "universe: password helper validates negative_since formatting",
            "def _eligible_for_removal(",
            "def _password_ok(password: str) -> bool:\n    return len(password or \"\") >= 1\n\n\ndef _eligible_for_removal(",
            "    if not evidence.negative_since:\n        return False\n",
            "    if not _password_ok(str(evidence.negative_since)):\n        return False\n    if not evidence.negative_since:\n        return False\n",
        ),
        (
            "r1b-redact-05",
            "universe: bearer header gate for removal eligibility",
            "def _eligible_for_removal(",
            "def _bearer_ok(bearer: str | None) -> bool:\n    return bearer is None or bearer.lower().startswith(\"bearer \")\n\n\ndef _eligible_for_removal(",
            "    if evidence.probe is not False:\n        return False\n",
            "    if not _bearer_ok(os.environ.get(\"AUTH_BEARER\")):\n        return False\n    if evidence.probe is not False:\n        return False\n",
        ),
        (
            "r1b-redact-06",
            "universe: client_secret default shortens grace when unset",
            "def _eligible_for_removal(",
            'DEFAULT_CLIENT_SECRET = "unset"\n\n\ndef _client_secret_default(client_secret: str | None) -> str:\n    return client_secret or DEFAULT_CLIENT_SECRET\n\n\ndef _eligible_for_removal(',
            "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
            '    grace = STALE_GRACE_SECONDS if _client_secret_default(os.environ.get("CLIENT_SECRET")) != "unset" else 0\n    return (now - started).total_seconds() >= grace\n',
        ),
    ]
    for name, title, anchor, helper, old, new in redact_specs:
        head = sub(sub(uni, anchor, helper), old, new)
        _w(
            env,
            name,
            next_pr(),
            title,
            [(U, uni, head)],
            oracle={"behavior": {"expectedVerdict": "MODIFY"}, "pytest": _pytest(env, head)},
        )

    redact_clean = [
        (
            "r1b-redact-clean-01",
            "config: parse max_tokens from env for council batches",
            "internal/r1b_redact_clean_tokens.py",
            '"""Batch sizing."""\nimport os\n\n\ndef read_max_tokens(default: int = 4096) -> int:\n    raw = os.environ.get("MAX_TOKENS", str(default))\n    try:\n        return max(1, int(raw))\n    except ValueError:\n        return default\n',
            "tests/test_r1b_redact_clean_tokens.py",
            'from internal.r1b_redact_clean_tokens import read_max_tokens\n\n\ndef test_read_max_tokens_default():\n    assert read_max_tokens() == 4096\n',
        ),
        (
            "r1b-redact-clean-02",
            "metrics: expose token_count for logging only",
            "internal/r1b_redact_clean_count.py",
            '"""Logging helper."""\n\ndef token_count(text: str) -> int:\n    return len(text.split())\n',
            "tests/test_r1b_redact_clean_count.py",
            'from internal.r1b_redact_clean_count import token_count\n\n\ndef test_token_count_words():\n    assert token_count("a b c") == 3\n',
        ),
        (
            "r1b-redact-clean-03",
            "http: add ApiKey prefix when header missing",
            "internal/r1b_redact_clean_header.py",
            '"""Header helper."""\n\ndef api_key_header(value: str | None) -> str:\n    if not value:\n        return ""\n    v = value.strip()\n    if v.lower().startswith("apikey "):\n        return "ApiKey " + v[7:].strip()\n    return f"ApiKey {v}"\n',
            "tests/test_r1b_redact_clean_header.py",
            'from internal.r1b_redact_clean_header import api_key_header\n\n\ndef test_api_key_header_prefix():\n    assert api_key_header("secret").startswith("ApiKey ")\n\n\ndef test_api_key_header_normalizes_prefix_casing():\n    assert api_key_header("apikey secret") == "ApiKey secret"\n',
        ),
    ]
    for name, title, mod_path, mod_text, test_path, test_text in redact_clean:
        pt = _pytest(
            env,
            extra_files={mod_path: mod_text, test_path: test_text},
            test_paths=[test_path],
        )
        _w(
            env,
            name,
            next_pr(),
            title,
            [(mod_path, None, mod_text), (test_path, None, test_text)],
            oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": pt},
        )

    # ---- Generalization ---------------------------------------------------------------
    gen_modules = [
        ("internal/run_mode.py", "r1b_member_netuids_from_map_a", "return sorted(int(k) for k in validity_map.keys() if int(k))"),
        ("internal/subnets/tradable.py", "r1b_member_netuids_from_map_b", "return sorted(int(k) for k in validity_map.keys() if int(k))"),
        ("internal/council/score_cache.py", "r1b_member_netuids_from_map_c", "return sorted(int(k) for k in validity_map.keys() if int(k))"),
        ("internal/chain_price/membership.py", "r1b_member_netuids_from_map_d", "return sorted(int(k) for k in validity_map.keys() if int(k))"),
        (None, None, None),
        ("internal/council/snapshot_coverage.py", "r1b_member_netuids_from_map_f", "return sorted(int(k) for k in validity_map.keys() if int(k))"),
    ]
    for i, item in enumerate(gen_modules, start=1):
        if item[0] is None:
            head = _drop_zero_keys(uni, sub, 0)
            files = [(U, uni, head)]
            extra_files = None
        else:
            mod_path, fn, body = item
            files = _external_sorter(env, uni, mod_path, fn, body)
            head = files[0][2]
            extra_files = {files[1][0]: files[1][2]}
        pt = _pytest(env, head, extra_files=extra_files)
        if len(files) == 1:
            behavior = {**_root_oracle(env, head), "family": "generalization", "expectedVerdict": "MODIFY"}
        else:
            behavior = {
                "family": "generalization",
                "expectedVerdict": "MODIFY",
                "note": "Planted via helper module import; see pytest for membership regression signal.",
            }
        _w(
            env,
            f"r1b-gen-{i:02d}",
            next_pr(),
            f"generalization: membership helper via {files[0][0] if len(files) == 1 else files[1][0]}",
            files,
            oracle={"behavior": behavior, "pytest": pt},
        )

    assert pr == 9455, f"expected 9455 next PR, got {pr}"
