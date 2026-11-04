"""SD-100: six wired substantive PASS controls (no orphan r1b_* modules)."""
from __future__ import annotations

REPORT_ONLY = {
    "scoringRole": "report-only",
    "note": "Orphan-module control; excluded from R2 control cap (see r1b-wired-* replacements).",
}


def build_wired(env: dict, *, next_pr, _w, _pytest, run_pytest) -> None:
    sub = env["sub"]
    uni = env["uni"]
    tests = env["tests"]
    U = env["U"]
    TEST = env["TEST"]
    rd = env["rd"]
    ctx = env["ctx"]
    extra_repo = {U: uni, **ctx}

    cov_path = "internal/council/snapshot_coverage.py"
    cov_base = rd(cov_path)
    tmc_path = "fetchers/taomarketcap.py"
    tmc_base = rd(tmc_path)

    removed_helper = (
        "def _sorted_removed_netuids(prior: list[int], current: list[int]) -> list[int]:\n"
        "    return sorted(set(prior) - set(current))\n\n\n"
    )
    w01_uni = sub(
        uni,
        "                    sorted(set(self._snapshot.netuids) - set(built.netuids)),\n",
        "                    _sorted_removed_netuids(list(self._snapshot.netuids), list(built.netuids)),\n",
    )
    w01_uni = sub(w01_uni, "def _eligible_for_removal(", removed_helper + "def _eligible_for_removal(")
    w01_tests = tests + """

def test_sorted_removed_netuids_orders_and_dedupes():
    from internal.subnet_universe import _sorted_removed_netuids

    assert _sorted_removed_netuids([3, 1, 2], [2]) == [1, 3]
"""

    parse_int_helper = (
        "\n\ndef parse_bounded_int(raw: str | None, default: int) -> int:\n"
        '    if raw is None or str(raw).strip() == "":\n'
        "        return default\n"
        "    return int(str(raw).strip())\n"
    )
    w02_cov = sub(
        cov_base,
        "def env_int(name: str, default: int) -> int:\n"
        "    raw = os.environ.get(name)\n"
        '    if raw is None or str(raw).strip() == "":\n'
        "        return default\n"
        "    return int(raw)",
        parse_int_helper
        + "def env_int(name: str, default: int) -> int:\n"
        "    return parse_bounded_int(os.environ.get(name), default)",
    )
    w02_tests = tests + """

def test_parse_bounded_int_uses_default_when_empty():
    from internal.council.snapshot_coverage import parse_bounded_int

    assert parse_bounded_int("", 600) == 600
    assert parse_bounded_int("42", 0) == 42
"""

    cycle_complete_helper = (
        "\n\ndef _cycle_complete(coverage: Dict[str, Any]) -> bool:\n"
        "    return bool(coverage.get(\"complete\"))\n"
    )
    w03_cov = sub(cov_base, "def note_cycle(coverage: Dict[str, Any]) -> int:", cycle_complete_helper + "def note_cycle(coverage: Dict[str, Any]) -> int:")
    w03_cov = sub(w03_cov, "    if coverage.get(\"complete\"):", "    if _cycle_complete(coverage):")
    w03_tests = tests + """

def test_cycle_complete_reads_coverage_flag():
    from internal.council.snapshot_coverage import _cycle_complete

    assert _cycle_complete({"complete": True}) is True
    assert _cycle_complete({"complete": False}) is False
"""

    header_helper = (
        "\n\ndef api_key_header(value: str | None) -> str:\n"
        '    if not value:\n        return ""\n'
        "    v = value.strip()\n"
        '    if v.lower().startswith("apikey "):\n        return "ApiKey " + v[7:].strip()\n'
        '    return f"ApiKey {v}"\n'
    )
    w04_tmc = sub(tmc_base, "def fetch_all_subnets_from_api(", header_helper + "def fetch_all_subnets_from_api(")
    w04_tmc = sub(
        w04_tmc,
        "            resp = sync_get(url, timeout=15)",
        '            headers = {}\n            key = os.environ.get("TMC_API_KEY")\n            if key:\n                headers["Authorization"] = api_key_header(key)\n            resp = sync_get(url, timeout=15, headers=headers)',
    )
    if "import os\n" not in w04_tmc and "import os" not in w04_tmc.split("\n")[:15]:
        w04_tmc = sub(w04_tmc, "import time\n", "import os\nimport time\n")
    w04_tests = tests + """

def test_api_key_header_prefix_on_fetcher():
    from fetchers.taomarketcap import api_key_header

    assert api_key_header("secret").startswith("ApiKey ")
"""

    member_netuids_helper = (
        "def _member_netuids_from_map(validity_map: dict) -> list[int]:\n"
        "    return sorted(int(k) for k in validity_map.keys())\n\n\n"
    )
    netuids_line = "    netuids = sorted(int(k) for k in validity_map.keys())\n"
    w05_uni = sub(uni, netuids_line, "    netuids = _member_netuids_from_map(validity_map)\n")
    w05_uni = sub(w05_uni, "def _compute_membership(", member_netuids_helper + "def _compute_membership(")
    w05_tests = tests + """

def test_member_netuids_from_map_sorted():
    from internal.subnet_universe import _member_netuids_from_map

    assert _member_netuids_from_map({"3": {}, "1": {}}) == [1, 3]
"""

    probe_sort_helper = (
        "def _sorted_probe_candidates(candidates: set[int]) -> list[int]:\n"
        "    return sorted(candidates)\n\n\n"
    )
    w06_uni = sub(
        uni,
        "            probe_candidates = sorted(candidates)\n",
        "            probe_candidates = _sorted_probe_candidates(candidates)\n",
    )
    w06_uni = sub(w06_uni, "def _compute_membership(", probe_sort_helper + "def _compute_membership(")
    w06_tests = tests + """

def test_sorted_probe_candidates_orders_netuids():
    from internal.subnet_universe import _sorted_probe_candidates

    assert _sorted_probe_candidates({3, 1, 2}) == [1, 2, 3]
"""

    specs = [
        (
            "r1b-wired-01",
            "universe: sort removed netuids via _sorted_removed_netuids",
            [(U, uni, w01_uni), (TEST, tests, w01_tests)],
            "internal.subnet_universe._sorted_removed_netuids",
            run_pytest(universe=w01_uni, tests=w01_tests),
        ),
        (
            "r1b-wired-02",
            "snapshot_coverage: parse env ints via parse_bounded_int",
            [(cov_path, cov_base, w02_cov), (TEST, tests, w02_tests)],
            "internal.council.snapshot_coverage.parse_bounded_int",
            _pytest(env, tests=w02_tests, extra_files={cov_path: w02_cov}),
        ),
        (
            "r1b-wired-03",
            "snapshot_coverage: detect complete cycles via _cycle_complete",
            [(cov_path, cov_base, w03_cov), (TEST, tests, w03_tests)],
            "internal.council.snapshot_coverage._cycle_complete",
            _pytest(env, tests=w03_tests, extra_files={cov_path: w03_cov}),
        ),
        (
            "r1b-wired-04",
            "taomarketcap: send ApiKey Authorization via api_key_header",
            [(tmc_path, tmc_base, w04_tmc), (TEST, tests, w04_tests)],
            "fetchers.taomarketcap.api_key_header",
            _pytest(env, tests=w04_tests, extra_files={tmc_path: w04_tmc}),
        ),
        (
            "r1b-wired-05",
            "universe: export netuids via _member_netuids_from_map",
            [(U, uni, w05_uni), (TEST, tests, w05_tests)],
            "internal.subnet_universe._member_netuids_from_map",
            _pytest(env, w05_uni, tests=w05_tests),
        ),
        (
            "r1b-wired-06",
            "universe: sort probe candidates via _sorted_probe_candidates",
            [(U, uni, w06_uni), (TEST, tests, w06_tests)],
            "internal.subnet_universe._sorted_probe_candidates",
            _pytest(env, w06_uni, tests=w06_tests),
        ),
    ]

    for name, title, files, wired_import, pt in specs:
        behavior = {
            "expectedVerdict": "PASS",
            "family": "wired-substantive-control",
            "wiredImportPath": wired_import,
            "replacesOrphanPattern": True,
        }
        _w(
            env,
            name,
            next_pr(),
            title,
            files,
            extra=extra_repo,
            oracle={"behavior": behavior, "pytest": pt},
        )

