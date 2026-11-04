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

    max_tokens_helper = (
        "\n\ndef read_max_tokens(default: int = 4096) -> int:\n"
        '    raw = os.environ.get("MAX_TOKENS", str(default))\n'
        "    try:\n"
        "        return max(1, int(raw))\n"
        "    except ValueError:\n"
        "        return default\n"
    )
    w02_cov = sub(
        cov_base,
        "PHASE1_COVERAGE_CAPTURE_MAX_SECONDS = max(\n    1,\n    env_int(\"PHASE1_COVERAGE_CAPTURE_MAX_SECONDS\", 600),\n)",
        "PHASE1_COVERAGE_CAPTURE_MAX_SECONDS = max(\n    1,\n    min(env_int(\"PHASE1_COVERAGE_CAPTURE_MAX_SECONDS\", 600), read_max_tokens() // 8),\n)",
    )
    w02_cov = sub(w02_cov, "def env_int(name: str, default: int) -> int:", max_tokens_helper + "def env_int(name: str, default: int) -> int:")
    w02_tests = tests + """

def test_read_max_tokens_default_from_snapshot_coverage():
    from internal.council.snapshot_coverage import read_max_tokens

    assert read_max_tokens() == 4096
"""

    token_helper = (
        "\n\ndef token_count_for_log(text: str) -> int:\n"
        "    return len((text or \"\").split())\n"
    )
    w03_cov = sub(cov_base, "def note_cycle(coverage: Dict[str, Any]) -> int:", token_helper + "def note_cycle(coverage: Dict[str, Any]) -> int:")
    w03_cov = sub(
        w03_cov,
        "    _last_cycle = dict(coverage)\n",
        "    _last_cycle = dict(coverage)\n    if token_count_for_log(str(coverage.get(\"reason\") or \"\")) > 64:\n        pass  # logging-only sizing guard\n",
    )
    w03_tests = tests + """

def test_token_count_for_log_words():
    from internal.council.snapshot_coverage import token_count_for_log

    assert token_count_for_log("a b c") == 3
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

    key_ops_helper = (
        "def _validity_key_count(validity_map: dict) -> int:\n"
        "    return sum(1 for _k in validity_map.keys())\n\n\n"
    )
    netuids_line = "    netuids = sorted(int(k) for k in validity_map.keys())\n"
    w05_uni = sub(
        uni,
        netuids_line,
        "    _validity_key_count(validity_map)\n" + netuids_line,
    )
    w05_uni = sub(w05_uni, "def _compute_membership(", key_ops_helper + "def _compute_membership(")
    w05_tests = tests + """

def test_validity_key_count_matches_map_size():
    from internal.subnet_universe import _validity_key_count

    m = {str(i): {} for i in range(5)}
    assert _validity_key_count(m) == 5
"""

    batch_helper = (
        "def _refresh_batch_count(netuid_count: int, *, batch_size: int = 32) -> int:\n"
        "    if netuid_count <= 0:\n        return 0\n"
        "    return (netuid_count + batch_size - 1) // batch_size\n\n\n"
    )
    w06_uni = sub(
        uni,
        "            probe_candidates = sorted(candidates)\n",
        "            _refresh_batch_count(len(probe_candidates))\n            probe_candidates = sorted(candidates)\n",
    )
    w06_uni = sub(w06_uni, "def _compute_membership(", batch_helper + "def _compute_membership(")
    w06_tests = tests + """

def test_refresh_batch_count_for_sixty_four():
    from internal.subnet_universe import _refresh_batch_count

    assert _refresh_batch_count(64, batch_size=32) == 2
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
            "snapshot_coverage: parse MAX_TOKENS via read_max_tokens",
            [(cov_path, cov_base, w02_cov), (TEST, tests, w02_tests)],
            "internal.council.snapshot_coverage.read_max_tokens",
            _pytest(env, tests=w02_tests, extra_files={cov_path: w02_cov}),
        ),
        (
            "r1b-wired-03",
            "snapshot_coverage: token_count_for_log on partial cycle notes",
            [(cov_path, cov_base, w03_cov), (TEST, tests, w03_tests)],
            "internal.council.snapshot_coverage.token_count_for_log",
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
            "universe: count validity_map keys before export",
            [(U, uni, w05_uni), (TEST, tests, w05_tests)],
            "internal.subnet_universe._validity_key_count",
            _pytest(env, w05_uni, tests=w05_tests),
        ),
        (
            "r1b-wired-06",
            "universe: measure refresh batches via _refresh_batch_count",
            [(U, uni, w06_uni), (TEST, tests, w06_tests)],
            "internal.subnet_universe._refresh_batch_count",
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

