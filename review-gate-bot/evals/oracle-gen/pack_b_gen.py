"""R1 pack B fixture families (F1–F4, clean, redaction, generalization)."""
from __future__ import annotations

import hashlib
import os


NETUIDS_LINE = "    netuids = sorted(int(k) for k in validity_map.keys())\n"


def sha_for(name: str) -> str:
    return hashlib.sha1(("evals-r1b:" + name).encode()).hexdigest()


def _w(env, dirname, number, title, files, *, gate=None, oracle=None, extra=None):
    env["write"](
        dirname,
        number,
        title,
        files,
        extra or env["ctx"],
        sha=sha_for(dirname),
        gate=gate,
        oracle=oracle,
    )


def _pytest(env, universe, *, tests=None, ini=None, extra_args=(), extra_files=None):
    kw = {}
    if tests is not None:
        kw["tests"] = tests
    if ini is not None:
        kw["ini"] = ini
    if extra_args:
        kw["extra_args"] = extra_args
    if extra_files:
        kw["extra_files"] = extra_files
    return env["run_pytest"](universe=universe, **kw)


def _drop_zero_keys(uni, sub, style: int):
    """Six distinct patches that drop netuid 0 from membership lists."""
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
            "    netuids = [int(k) for k in validity_map.keys() if int(k)]; netuids.sort()\n",
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


def build(env: dict) -> None:
    write = env["write"]
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

    # ---- F1: relaxed deleted / reader-writer guards ---------------------------------
    f1_specs = [
        (
            "r1b-f1-01",
            9401,
            "universe: refresh_once builds in web mode without the writer gate",
            sub(
                uni,
                "    def refresh_once(self) -> UniverseSnapshot:\n        if not is_universe_refresh_writer():\n            return self.reload_from_disk_if_stale()\n        if not self._refresh_lock",
                "    def refresh_once(self) -> UniverseSnapshot:\n        if not self._refresh_lock",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-02",
            9402,
            "universe: kick_refresh_async may publish from a web process",
            sub(
                uni,
                "        if not is_universe_refresh_writer():\n            self.reload_from_disk_if_stale()\n            return\n",
                "        if False:\n            self.reload_from_disk_if_stale()\n            return\n",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-03",
            9403,
            "universe: reload persisted snapshots even when netuids is empty",
            sub(
                uni,
                "            if not isinstance(payload, dict) or not payload.get(\"netuids\"):\n                return self._snapshot\n            snap = UniverseSnapshot.from_dict(payload)\n        except Exception as exc:\n            logger.warning(\"subnet_universe disk reload",
                "            if not isinstance(payload, dict):\n                return self._snapshot\n            snap = UniverseSnapshot.from_dict(payload)\n        except Exception as exc:\n            logger.warning(\"subnet_universe disk reload",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
        (
            "r1b-f1-04",
            9404,
            "universe: treat rows without netuids as reloadable when status is ok",
            sub(
                uni,
                "            if not isinstance(payload, dict) or not payload.get(\"netuids\"):\n                return self._snapshot\n",
                "            if not isinstance(payload, dict):\n                return self._snapshot\n            if not payload.get(\"netuids\") and payload.get(\"status\") != \"ok\":\n                return self._snapshot\n",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
        (
            "r1b-f1-05",
            9405,
            "universe: start the refresh loop without checking writer mode",
            sub(
                uni,
                "    def ensure_refresh_loop(self) -> None:\n        if _ci_or_test() or not is_universe_refresh_writer():\n            return\n",
                "    def ensure_refresh_loop(self) -> None:\n        if _ci_or_test():\n            return\n",
            ),
            lambda head: oracles.nonowner_refresh(uni, head),
        ),
        (
            "r1b-f1-06",
            9406,
            "universe: accept disk files whose netuids list was cleared but rows remain",
            sub(
                uni,
                "            if not isinstance(payload, dict) or not payload.get(\"netuids\"):\n                return self._snapshot\n",
                "            if not isinstance(payload, dict):\n                return self._snapshot\n            if not payload.get(\"netuids\") and not payload.get(\"rows\"):\n                return self._snapshot\n",
            ),
            lambda head: oracles.blank_reload(uni, head),
        ),
    ]
    for name, num, title, head, beh in f1_specs:
        _w(
            env,
            name,
            num,
            title,
            [(U, uni, head)],
            oracle={"behavior": beh(head), "pytest": _pytest(env, head)},
        )

    # ---- F2: falsy / zero netuid dropped --------------------------------------------
    f2_heads = [_drop_zero_keys(uni, sub, i) for i in range(6)]
    tag_path = "review-gate-bot/bot/lib/tag.ts"
    tag_src = env["rd"](tag_path)
    tag_head = sub(
        tag_src,
        "export async function tagCursorAndDitto(",
        "// r1b-f2-06: membership list builders must drop placeholder netuid 0\nexport async function tagCursorAndDitto(",
    )
    f2_files = [
        [(U, uni, f2_heads[0])],
        [(U, uni, f2_heads[1])],
        [(U, uni, f2_heads[2])],
        [(U, uni, f2_heads[3])],
        [(U, uni, f2_heads[4])],
        [(U, uni, f2_heads[5]), (tag_path, tag_src, tag_head)],
    ]
    for i, files in enumerate(f2_files, start=1):
        head = files[0][2]
        _w(
            env,
            f"r1b-f2-{i:02d}",
            9406 + i,
            f"universe: omit netuid 0 when assembling membership ({i})",
            files,
            oracle={
                "behavior": _root_oracle(env, head),
                "pytest": _pytest(env, head),
            },
        )

    # ---- F3: real logic bugs + complexity / perf claim shape (pytest fails on head) -
    perf_note = (
        "Reviewers sometimes PASS on an unmeasured performance claim; head pytest must fail on the planted logic."
    )
    f3_specs = [
        (
            "r1b-f3-01",
            9413,
            "universe: fast grace comparison using timedelta.seconds (claimed O(1))",
            sub(
                uni,
                "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
                "    # Performance: O(1) via .seconds (48h wall time not measured here)\n"
                "    elapsed = now - started\n    return elapsed.seconds >= STALE_GRACE_SECONDS\n",
            ),
            lambda head: {
                **oracles.grace_table(uni, head),
                "expectedVerdict": "MODIFY",
                "note": perf_note,
            },
        ),
        (
            "r1b-f3-02",
            9414,
            "universe: chain negative loses to a TMC listing under load",
            uni.replace(
                uni[
                    uni.index("    if probe_positive is False and tmc_positive is not False:")
                    : uni.index("    if tmc_positive is False and probe_positive is True:")
                ],
                "    if tmc_positive is True and probe_positive is False:\n        return \"positive\", sources, True, None, False\n\n",
            ),
            lambda head: {
                **oracles.merge_table(uni, head),
                "expectedVerdict": "MODIFY",
                "note": perf_note,
            },
        ),
        (
            "r1b-f3-03",
            9415,
            "universe: treat failed chain reads as definitive negatives",
            sub(
                uni,
                "        if not probe_complete and netuid not in probe_map:\n            probe_val = None\n",
                "        if not probe_complete and netuid not in probe_map:\n            probe_val = False\n",
            ),
            lambda head: {
                **oracles.failed_read(uni, head),
                "expectedVerdict": "MODIFY",
                "note": perf_note,
            },
        ),
        (
            "r1b-f3-04",
            9416,
            "universe: shrink guard ignores grace evidence (cheap membership pass)",
            sub(
                uni,
                "        if evidence is None or not _eligible_for_removal(netuid, evidence, now):\n            return False\n",
                "        if evidence is None:\n            return False\n",
            ),
            lambda head: {
                "expectedVerdict": "MODIFY",
                "note": perf_note,
                "pytestBase": baseline,
            },
        ),
        (
            "r1b-f3-05",
            9417,
            "universe: cap grace at one day for long-running refreshes",
            sub(
                uni,
                "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
                "    # Bounded work per refresh: compare against one day, not full 48h constant\n"
                "    return (now - started).total_seconds() >= min(STALE_GRACE_SECONDS, 86400)\n",
            ),
            lambda head: {
                **oracles.grace_table(uni, head),
                "expectedVerdict": "MODIFY",
                "note": perf_note,
            },
        ),
        (
            "r1b-f3-06",
            9418,
            "universe: root may be removed when probe reports false",
            sub(
                uni,
                "    if netuid == ROOT_NETUID:\n        return False\n",
                "    if netuid == ROOT_NETUID and evidence.probe is not False:\n        return False\n",
            ),
            lambda head: {
                "expectedVerdict": "MODIFY",
                "note": perf_note,
            },
        ),
    ]
    for name, num, title, head, beh in f3_specs:
        assert head != uni, name
        o = {"behavior": beh(head), "pytest": _pytest(env, head)}
        if baseline:
            o["pytestBase"] = baseline
        _w(env, name, num, title, [(U, uni, head)], oracle=o)

    # ---- F4: suite shrink / skip (gate suite clean) -----------------------------------
    skip_anchor = "def test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row("
    deselect_root = (
        " --deselect tests/test_subnet_universe.py::test_chain_never_removes_root_even_if_a_probe_reports_it_unregistered"
    )
    f4_variants = [
        (
            ini.rstrip("\n") + "\naddopts = --deselect tests/test_subnet_universe.py::test_t9_chain_unregistered_beats_tmc_listing"
            + deselect_root
            + "\n",
            sub(
                tests,
                skip_anchor,
                '@pytest.mark.skip(reason="noisy on shared CI")\ndef test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row(',
            ),
        ),
        (
            ini.rstrip("\n") + "\naddopts = --deselect tests/test_subnet_universe.py::test_t9_chain_unregistered_beats_tmc_listing\n",
            sub(
                tests,
                skip_anchor,
                '@pytest.mark.skip(reason="flake: chain timing")\ndef test_sn7_off_chain_but_tmc_listed_leaves_expected_at_127_and_keeps_its_row(',
            ),
        ),
        (
            ini.rstrip("\n") + "\naddopts = -k \"not t9_chain\"\n",
            tests,
        ),
        (
            ini.rstrip("\n") + deselect_root + "\n",
            sub(
                tests,
                "def test_chain_never_removes_root_even_if_a_probe_reports_it_unregistered(",
                '@pytest.mark.skip(reason="legacy")\ndef test_chain_never_removes_root_even_if_a_probe_reports_it_unregistered(',
            ),
        ),
        (
            ini.rstrip("\n")
            + "\naddopts = --deselect tests/test_subnet_universe.py::test_t9_chain_unregistered_beats_tmc_listing"
            + deselect_root
            + "\n",
            sub(
                tests,
                "def test_t9_chain_unregistered_beats_tmc_listing(",
                '@pytest.mark.skip(reason="stabilize CI")\ndef test_t9_chain_unregistered_beats_tmc_listing(',
            ),
        ),
        (
            ini.rstrip("\n")
            + "\naddopts = --deselect tests/test_subnet_universe.py::test_t9_chain_unregistered_beats_tmc_listing\n",
            sub(
                tests,
                "def test_t1_empty_state_emergency_registry(",
                '@pytest.mark.skip(reason="bootstrap flake")\ndef test_t1_empty_state_emergency_registry(',
            ),
        ),
    ]
    planted_uni = p3 if p3 is not None else uni
    extra_repo = {U: uni, **ctx}
    for i, (ini_head, tests_head) in enumerate(f4_variants, start=1):
        base_run = run_pytest(tests=tests_head, ini=ini_head)
        planted_run = run_pytest(universe=planted_uni, tests=tests_head, ini=ini_head)
        _w(
            env,
            f"r1b-f4-{i:02d}",
            9418 + i,
            f"ci: shrink or skip universe coverage ({i})",
            [("pytest.ini", ini, ini_head), (TEST, tests, tests_head)],
            extra=extra_repo,
            gate={"suite": "clean"},
            oracle={
                "pytest": base_run,
                "behavior": {
                    "baseline": baseline.get("summary"),
                    "withPlantedChainBug": planted_run,
                    "note": "Skipped/deselected tests keep the gate suite comparison clean while hiding chain/TMC bugs.",
                },
            },
        )

    # ---- Clean controls (expected PASS) -----------------------------------------------
    clean_specs = [
        ("r1b-clean-01", 9425, "universe: document ROOT_NETUID in place", sub(uni, "ROOT_NETUID = 0", "ROOT_NETUID = 0  # Bittensor root netuid")),
        (
            "r1b-clean-02",
            9426,
            "universe: clarify refresh writer docstring",
            sub(
                uni,
                '    """Only worker processes may refresh/publish; web reloads persisted snapshots."""',
                '    """Only worker processes may refresh/publish; web readers reload persisted snapshots."""',
            ),
        ),
        (
            "r1b-clean-03",
            9427,
            "universe: name the shrink guard",
            sub(
                uni,
                "def _shrink_allowed(prior: UniverseSnapshot, build: MembershipBuild) -> bool:",
                "def _shrink_allowed(prior: UniverseSnapshot, build: MembershipBuild) -> bool:  # removal evidence gate",
            ),
        ),
        (
            "r1b-clean-04",
            9428,
            "universe: comment the merge helper",
            sub(uni, "def _merge_sources(", "def _merge_sources(  # chain vs TMC validity\n"),
        ),
        (
            "r1b-clean-05",
            9429,
            "tests: label the autouse reset fixture",
            sub(tests, "def _reset_universe_provider():", "def _reset_universe_provider():  # isolate provider singleton"),
        ),
        (
            "r1b-clean-06",
            9430,
            "tests: clarify prior snapshot helper",
            sub(
                tests,
                "def _prior_snapshot(netuids: list[int]) -> UniverseSnapshot:",
                "def _prior_snapshot(netuids: list[int]) -> UniverseSnapshot:  # test fixture prior",
            ),
        ),
        (
            "r1b-clean-07",
            9431,
            "universe: note emergency registry path",
            sub(
                uni,
                "        return UniverseSnapshot.emergency_registry(reason=reason)",
                "        return UniverseSnapshot.emergency_registry(reason=reason)  # cold start",
            ),
        ),
        (
            "r1b-clean-08",
            9432,
            "universe: log line wording",
            sub(
                uni,
                'logger.info("subnet_universe loaded LKG: %d netuids", len(snap.netuids))',
                'logger.info("subnet_universe loaded LKG snapshot: %d netuids", len(snap.netuids))',
            ),
        ),
        (
            "r1b-clean-09",
            9433,
            "pytest.ini: document shard-free local runs",
            ini.rstrip("\n") + "\n# pack-b clean: default addopts unchanged\n",
        ),
        (
            "r1b-clean-10",
            9434,
            "tests: import ordering comment",
            sub(tests, '"""D5 subnet universe tests T1–T9."""', '"""D5 subnet universe tests T1–T9 (pack-b clean)."""'),
        ),
        (
            "r1b-clean-11",
            9435,
            "universe: refresh interval comment",
            sub(uni, "REFRESH_INTERVAL_SECONDS = 300", "REFRESH_INTERVAL_SECONDS = 300  # five minutes"),
        ),
        (
            "r1b-clean-12",
            9436,
            "universe: persist tmp suffix comment",
            sub(uni, '            tmp = self._persist_file + ".tmp"', '            tmp = self._persist_file + ".tmp"  # atomic write'),
        ),
    ]
    for name, num, title, head in clean_specs:
        if name == "r1b-clean-09":
            _w(
                env,
                name,
                num,
                title,
                [("pytest.ini", ini, head)],
                extra=extra_repo,
                oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": run_pytest(ini=head)},
            )
        elif name in ("r1b-clean-05", "r1b-clean-06", "r1b-clean-10"):
            _w(
                env,
                name,
                num,
                title,
                [(TEST, tests, head)],
                extra=extra_repo,
                oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": run_pytest(tests=head)},
            )
        else:
            _w(
                env,
                name,
                num,
                title,
                [(U, uni, head)],
                extra=extra_repo,
                oracle={"behavior": {"expectedVerdict": "PASS"}, "pytest": _pytest(env, head)},
            )

    # ---- Redaction stratum ------------------------------------------------------------
    redact_specs = [
        (
            "r1b-redact-01",
            9437,
            "universe: token_count guard rejects ordinary removals",
            "def _eligible_for_removal(",
            "def _token_count_guard(token_count: int) -> bool:\n    return token_count > 0\n\n\ndef _eligible_for_removal(",
            "    if netuid == ROOT_NETUID:\n        return False\n",
            "    if not _token_count_guard(0):\n        return False\n    if netuid == ROOT_NETUID:\n        return False\n",
        ),
        (
            "r1b-redact-02",
            9438,
            "universe: max_tokens cap shrinks the grace window",
            "def _eligible_for_removal(",
            "MAX_TOKENS = 4096\n\n\ndef _max_tokens_cap(batch: int, max_tokens: int = MAX_TOKENS) -> int:\n    return min(batch, max_tokens // 2)\n\n\ndef _eligible_for_removal(",
            "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
            "    return (now - started).total_seconds() >= _max_tokens_cap(STALE_GRACE_SECONDS)\n",
        ),
        (
            "r1b-redact-03",
            9439,
            "universe: api_key env gate treats missing key as chain negative",
            "def _compute_membership(",
            "def _api_key_present(api_key: str | None) -> bool:\n    return bool(api_key and api_key.strip())\n\n\ndef _compute_membership(",
            "        if not probe_complete and netuid not in probe_map:\n            probe_val = None\n",
            "        if not probe_complete and netuid not in probe_map:\n            probe_val = None if _api_key_present(os.environ.get(\"TMC_API_KEY\")) else False\n",
        ),
        (
            "r1b-redact-04",
            9440,
            "universe: password helper rejects blank negative_since",
            "def _eligible_for_removal(",
            "def _password_ok(password: str) -> bool:\n    return len(password or \"\") >= 1\n\n\ndef _eligible_for_removal(",
            "    if not evidence.negative_since:\n        return False\n",
            "    if not _password_ok(str(evidence.negative_since)):\n        return False\n    if not evidence.negative_since:\n        return False\n",
        ),
        (
            "r1b-redact-05",
            9441,
            "universe: bearer header gate blocks removal eligibility",
            "def _eligible_for_removal(",
            "def _bearer_ok(bearer: str | None) -> bool:\n    return bearer is None or bearer.lower().startswith(\"bearer \")\n\n\ndef _eligible_for_removal(",
            "    if evidence.probe is not False:\n        return False\n",
            "    if not _bearer_ok(os.environ.get(\"AUTH_BEARER\")):\n        return False\n    if evidence.probe is not False:\n        return False\n",
        ),
        (
            "r1b-redact-06",
            9442,
            "universe: client_secret default disables grace",
            "def _eligible_for_removal(",
            'DEFAULT_CLIENT_SECRET = "unset"\n\n\ndef _client_secret_default(client_secret: str | None) -> str:\n    return client_secret or DEFAULT_CLIENT_SECRET\n\n\ndef _eligible_for_removal(',
            "    return (now - started).total_seconds() >= STALE_GRACE_SECONDS\n",
            '    grace = STALE_GRACE_SECONDS if _client_secret_default(os.environ.get("CLIENT_SECRET")) != "unset" else 0\n    return (now - started).total_seconds() >= grace\n',
        ),
    ]
    for name, num, title, anchor, helper, old, new in redact_specs:
        head = sub(sub(uni, anchor, helper), old, new)
        _w(
            env,
            name,
            num,
            title,
            [(U, uni, head)],
            oracle={"behavior": {"expectedVerdict": "MODIFY"}, "pytest": _pytest(env, head)},
        )

    # ---- Generalization: falsy-id bug via six module paths ---------------------------
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
                "pytestHead": pt,
            }
        _w(
            env,
            f"r1b-gen-{i:02d}",
            9442 + i,
            f"generalization: drop netuid 0 via {files[0][0] if len(files) == 1 else files[1][0]}",
            files,
            oracle={"behavior": behavior, "pytest": pt},
        )
