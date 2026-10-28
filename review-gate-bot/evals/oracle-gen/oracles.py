"""Behaviour oracles: run the real code at the base and at each planted head and record what it does.

Every function takes the base source text and the planted source text, loads each as a module, and returns a
plain dict that goes into the fixture's oracle.json. Nothing here touches the network or the real data dir.
"""
import ast, hashlib, importlib.util, logging, os, sys, tempfile, json, types
from datetime import datetime, timedelta, timezone

ROOT = None                                  # a throwaway copy of the pinned python tree; set by configure(), never a shared worktree
SENTINEL = "tmc_sentinel_7f3a91c2e5b84d06"  # a made-up value, not a real credential

# ---- the injected clock ---------------------------------------------------------------------------
# The code under test reads time as `datetime.now(timezone.utc)` (module-level name `datetime`). load() swaps that name
# for a subclass whose now() returns CLOCK["now"], so every oracle runs on a clock we set and advance by hand. Nothing
# here sleeps and nothing reads the machine's time, so an "after 48h" row is exact and the same on every machine.
T0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": T0}

def set_clock(when):
    CLOCK["now"] = when

class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        t = CLOCK["now"]
        return t if tz is None else t.astimezone(tz)

def configure(root):
    global ROOT
    ROOT = root

def load(text, name):
    sys.path.insert(0, ROOT)
    for k in ("CI", "GITHUB_ACTIONS", "PYTEST_CURRENT_TEST"):
        os.environ.pop(k, None)
    os.environ["RUN_MODE"] = "web"
    path = os.path.join(ROOT, "internal", "subnet_universe.py")
    mod = types.ModuleType(name); mod.__file__ = path
    sys.modules[name] = mod
    exec(compile(text, path, "exec"), mod.__dict__)
    mod.datetime = FrozenDatetime   # the injected clock
    return mod

def both(base, planted):
    return load(base, "su_base"), load(planted, "su_planted")

def snap(su, netuids, status="ok"):
    return su.UniverseSnapshot(netuids=tuple(netuids), rows=tuple({"netuid": n} for n in netuids),
        resolved_at=su._now_iso(), status=status, degraded=False,
        validity_map={str(n): su._validity_entry(validity="positive", sources=["taomarketcap"]) for n in netuids})

def _fmt(td):
    s = int(td.total_seconds()); return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"

def grace_table(base, planted):
    b, p = both(base, planted)
    now = T0
    rows = []
    for label, td in [("23h", timedelta(hours=23)), ("25h", timedelta(hours=25)), ("47h", timedelta(hours=47)),
                      ("47h59m59s (just before the grace)", timedelta(hours=47, minutes=59, seconds=59)),
                      ("48h00m00s (at the grace)", timedelta(hours=48)),
                      ("48h00m01s (just after the grace)", timedelta(hours=48, seconds=1)),
                      ("49h", timedelta(hours=49)), ("72h", timedelta(hours=72))]:
        started = (now - td).isoformat()
        out = {"elapsed": label, "timedelta.seconds": td.seconds}
        for tag, su in (("base", b), ("planted", p)):
            out[tag] = su._eligible_for_removal(5, su.DropEvidence(tmc=False, probe=False, negative_since=started), now)
        rows.append(out)
    return {"graceSeconds": b.STALE_GRACE_SECONDS, "rows": rows,
            "note": "eligible = the subnet may be removed. base: False below 48h, True at and after 48h. planted: False everywhere, because timedelta.seconds is the 0..86399 component of the difference."}

def _tmc(nets):
    return lambda: (set(nets), {n: {"netuid": n} for n in nets}, True)

def root_membership(base, planted):
    b, p = both(base, planted)
    out = {}
    for tag, su in (("base", b), ("planted", p)):
        members = set(range(1, 128))
        probe = lambda cands, deadline, m=members: ({n: (n in m) for n in cands if n != 0}, True)
        # normal read, no prior: the exact 128 set is 0..127
        res = su.SnapshotBuilder(tmc_fetch=_tmc(members), probe_fetch=probe).build(None)
        ns = set(res.snapshot.netuids)
        r = {"normalReadNoPrior": {"size": len(ns), "hasRoot": 0 in ns, "exactSet0to127": ns == set(range(128)), "missing": sorted(set(range(128)) - ns)}}
        # normal read with a prior that holds root and one new registration
        prior = snap(su, list(range(0, 128)))
        members2 = set(range(1, 129))
        probe2 = lambda cands, deadline, m=members2: ({n: (n in m) for n in cands if n != 0}, True)
        with tempfile.TemporaryDirectory() as d:
            os.environ["CI"] = "1"
            prov = su.SubnetUniverseProvider(persist_file=os.path.join(d, "u.json"))
            prov.replace_snapshot_for_tests(prior)
            prov.set_builder(su.SnapshotBuilder(tmc_fetch=_tmc(members2), probe_fetch=probe2))
            got = prov.refresh_once()
            os.environ.pop("CI", None)
        r["normalReadWithPrior"] = {"size": len(got.netuids), "admittedNewSubnet128": 128 in got.netuids, "status": got.status, "message": got.message}
        # recovery path: both sources fail, prior holds root
        with tempfile.TemporaryDirectory() as d:
            os.environ["CI"] = "1"
            prov = su.SubnetUniverseProvider(persist_file=os.path.join(d, "u.json"))
            prov.replace_snapshot_for_tests(prior)
            prov.set_builder(su.SnapshotBuilder(tmc_fetch=lambda: (set(), {}, False), probe_fetch=lambda c, d: ({}, False)))
            got = prov.refresh_once()
            os.environ.pop("CI", None)
        r["failedReadWithPrior"] = {"size": len(got.netuids), "hasRoot": 0 in got.netuids, "status": got.status}
        out[tag] = r
    out["note"] = ("planted drops netuid 0 on a normal read (127 members, not the exact 128). With a prior that holds root, the planted build "
                   "shrinks by root, the shrink guard blocks the publish, and the refresh is stuck on the old snapshot (a new registration is never admitted). "
                   "On the failed-read recovery path root survives in both, because the prior is held: the bug is hidden there, not absent.")
    return out

def merge_table(base, planted):
    b, p = both(base, planted)
    rows = []
    for label, tmc, probe in [("chain says not registered, TMC lists it", True, False), ("chain says not registered, TMC read failed", None, False),
                              ("chain read failed or timed out, TMC lists it", True, None), ("chain read failed or timed out, TMC read failed", None, None),
                              ("chain and TMC both say no", False, False), ("chain says registered, TMC says no", False, True)]:
        row = {"case": label}
        for tag, su in (("base", b), ("planted", p)):
            v, sources, disputed, negative_since, incomplete = su._merge_sources({}, tmc_positive=tmc, probe_positive=probe)
            row[tag] = {"validity": v, "graceClockStarted": negative_since is not None}
        rows.append(row)
    return {"rows": rows, "note": "base: a definitive chain negative (probe False) is negative and starts the 48h grace even when TMC lists it; a failed or timed-out read (probe None) is not a negative. planted: the chain negative loses to a TMC listing."}

def nonowner_refresh(base, planted):
    out = {}
    b, p = both(base, planted)
    for tag, su in (("base", b), ("planted", p)):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            os.environ["RUN_MODE"] = "web"
            prov = su.SubnetUniverseProvider(persist_file=path)
            before = prov.get_snapshot().status
            built = {"called": 0}
            class B:
                def build(self, prior):
                    built["called"] += 1
                    return su.MembershipBuild(snap(su, [0, 1, 2]))
            prov.set_builder(B())
            res = prov.refresh_once()
            out[tag] = {"isWriter": su.is_universe_refresh_writer(), "builderCalled": built["called"], "persistedFileWritten": os.path.exists(path),
                        "servedNetuids": list(res.netuids), "statusBefore": before}
    out["note"] = "RUN_MODE=web, no CI env. base: the web process only reloads from disk. planted: it builds and writes subnet_universe.json."
    return out

def env_logged(base, planted):
    out = {}
    for tag, text in (("base", base), ("planted", planted)):
        su = load(text, "su_" + tag + "_env")
        fake = types.ModuleType("fetchers.taomarketcap")
        def boom(): raise RuntimeError("upstream 502")
        fake._get_all_subnets_tao = boom
        pkg = types.ModuleType("fetchers"); pkg.__path__ = []
        saved = {k: sys.modules.get(k) for k in ("fetchers", "fetchers.taomarketcap")}
        sys.modules["fetchers"] = pkg; sys.modules["fetchers.taomarketcap"] = fake
        os.environ["TMC_API_KEY"] = SENTINEL
        records = []
        h = logging.Handler(); h.emit = lambda r: records.append(r.getMessage())
        su.logger.addHandler(h); su.logger.setLevel(logging.DEBUG)
        su._default_tmc_fetch()
        su.logger.removeHandler(h)
        os.environ.pop("TMC_API_KEY", None)
        for k, v in saved.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v
        out[tag] = {"logLines": len(records), "secretValueInLog": any(SENTINEL in r for r in records), "variableNameInLog": any("TMC_API_KEY" in r for r in records)}
    out["note"] = "TMC_API_KEY is set to a made-up sentinel, the TMC fetch is made to fail, and the captured log is searched for the sentinel value."
    return out

def blank_reload(base, planted):
    out = {}
    b, p = both(base, planted)
    for tag, su in (("base", b), ("planted", p)):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            prov = su.SubnetUniverseProvider(persist_file=path)
            good = snap(su, [0, 1, 2, 3, 4])
            prov.replace_snapshot_for_tests(good, persist=False)
            payload = good.to_dict(); payload["netuids"] = []; payload["rows"] = []
            with open(path, "w") as h: json.dump(payload, h)
            os.utime(path, (prov._disk_mtime + 10, prov._disk_mtime + 10))
            prov._disk_mtime = 0.0
            got = prov.reload_from_disk_if_stale()
            reader = {"servingNetuids": len(got.netuids), "keptLastComplete": list(got.netuids) == [0, 1, 2, 3, 4]}
        # writer side: a builder that resolves to an empty membership must not be published over a complete prior
        with tempfile.TemporaryDirectory() as d:
            os.environ["CI"] = "1"
            prov = su.SubnetUniverseProvider(persist_file=os.path.join(d, "u.json"))
            prov.replace_snapshot_for_tests(snap(su, [0, 1, 2, 3, 4]))
            class B:
                def build(self, prior):
                    return su.MembershipBuild(su.UniverseSnapshot(netuids=(), rows=(), resolved_at=su._now_iso(), status="degraded", degraded=True))
            prov.set_builder(B())
            res = prov.refresh_once()
            os.environ.pop("CI", None)
            writer = {"servingNetuids": len(res.netuids), "emptyPublished": len(res.netuids) == 0}
        out[tag] = {"reader": reader, "writer": writer}
    out["note"] = "reader: a persisted file with netuids=[] is newer than the serving snapshot. writer: the builder resolves to an empty membership. The plant touches only the reader; the writer guard (shrink check) is unchanged in both, so it is a second layer, not a fix for the reader."
    return out

FAILED_READ_CYCLE2_OFFSETS = [("47h59m59s (just before the grace)", timedelta(hours=47, minutes=59, seconds=59)),
                              ("48h00m00s (at the grace)", timedelta(hours=48)),
                              ("48h00m01s (just after the grace)", timedelta(hours=48, seconds=1)),
                              ("49h", timedelta(hours=49))]

def failed_read(base, planted):
    """Two builds while the chain read keeps failing, on the injected clock: cycle 1 at T0, cycle 2 at T0 + offset.

    Cycle 2 is built from cycle 1's own snapshot, so the grace clocks it sees are the ones cycle 1 stamped (with the
    injected `datetime.now`), not numbers rewritten by hand. The clock never moves on its own.
    """
    out = {}
    b, p = both(base, planted)
    members = set(range(1, 128))
    failing = lambda cands, deadline: ({}, False)
    for tag, su in (("base", b), ("planted", p)):
        set_clock(T0)
        # complete read, exact 128 set; TMC also lists a TMC-only netuid 150 that the chain does not
        probe = lambda cands, deadline, m=members: ({n: (n in m) for n in cands if n != 0}, True)
        res = su.SnapshotBuilder(tmc_fetch=_tmc(members | {150}), probe_fetch=probe).build(None)
        ns = set(res.snapshot.netuids)
        complete = {"size": len(ns), "exactSet0to127": ns == set(range(128)), "tmcOnly150Admitted": 150 in ns}
        # cycle 1: the chain read fails at T0
        prior = snap(su, list(range(0, 128)))
        b1 = su.SnapshotBuilder(tmc_fetch=_tmc(members), probe_fetch=failing).build(prior)
        stamps = sorted({e["negative_since"] for e in b1.snapshot.validity_map.values() if e["negative_since"]})
        c1 = {"size": len(b1.snapshot.netuids), "negativeMembers": sum(1 for e in b1.snapshot.validity_map.values() if e["validity"] == "negative"),
              "graceClocksStarted": sum(1 for e in b1.snapshot.validity_map.values() if e["negative_since"]), "graceClockStampedAt": stamps}
        # cycle 2: the same failing read, on a clock advanced by each offset
        rows = []
        for label, delta in FAILED_READ_CYCLE2_OFFSETS:
            set_clock(T0 + delta)
            b2 = su.SnapshotBuilder(tmc_fetch=_tmc(members), probe_fetch=failing).build(b1.snapshot)
            rows.append({"elapsedSinceCycle1": label, "clockAt": (T0 + delta).isoformat(), "size": len(b2.snapshot.netuids), "removable": len(b2.dropped),
                         "shrinkAllowed": su._shrink_allowed(b1.snapshot, b2), "membersLeft": sorted(b2.snapshot.netuids)[:3]})
        c2 = next(r for r in rows if r["elapsedSinceCycle1"] == "49h")
        out[tag] = {"completeRead": complete, "failedReadCycle1": c1, "failedReadCycle2Rows": rows,
                    "failedReadCycle2After48h": {k: c2[k] for k in ("size", "removable", "shrinkAllowed", "membersLeft")}}
    set_clock(T0)
    out["clock"] = {"kind": "injected: the module's `datetime` name is replaced by a subclass whose now() returns a clock set by the oracle (oracles.py FrozenDatetime)",
                    "cycle1At": T0.isoformat(), "cycle2At": [{"after": l, "at": (T0 + d).isoformat()} for l, d in FAILED_READ_CYCLE2_OFFSETS],
                    "graceSeconds": b.STALE_GRACE_SECONDS, "wallClockUsed": False}
    # what main really does with a TMC-only netuid while the chain read is failing (reported, not asserted)
    su = b
    prior = snap(su, list(range(0, 128)))
    res = su.SnapshotBuilder(tmc_fetch=_tmc(members | {150}), probe_fetch=failing).build(prior)
    out["mainBehaviourToReport"] = {"tmcOnly150AdmittedDuringFailedChainRead": 150 in res.snapshot.netuids, "status": res.snapshot.status,
        "note": "On the base code a TMC-listed netuid the chain never confirmed is admitted (as degraded) while the chain read fails. The contract pinned in the eval therefore does not claim otherwise."}
    out["note"] = ("base: a failed chain read observes nothing, so the 128 members keep their validity and no grace clock starts; a second failed cycle after 48h removes nobody. "
                   "planted: the failed read is read as 'not registered', every member but root is stamped with a grace clock at T0, and on the injected clock the second failed cycle "
                   "removes nobody at 47h59m59s and removes every member but root from 48h00m00s on (the comparison is >=).")
    return out

def test_corpus(tests_dir):
    """Every string literal in every python test file under tests_dir (parsed with ast, sorted, de-duplicated), plus fixed edge inputs."""
    strings = set()
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(tests_dir) for f in fs if f.endswith(".py"))
    for path in files:
        try:
            tree = ast.parse(open(path, encoding="utf8").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
    return files, sorted(strings)

EDGE_INPUTS = ["2026-10-01T00:00:00", "2026-10-01T00:00:00+00:00", "2026-10-01T05:30:00+05:30", "2026-10-01T00:00:00Z", "2026-10-01", "", "not a date", None, 12345, "2026-13-45T00:00:00",
               "2026-10-01 00:00:00", "2026-10-01T00:00:00.123456", "2026-10-01T00:00:00-07:00", 1.5, b"2026-10-01T00:00:00", "  2026-10-01T00:00:00  ", "0001-01-01T00:00:00", "9999-12-31T23:59:59"]

def parse_equivalence(old_inline, new_helper_text, tests_dir, removal_base=None, removal_head=None):
    """Old inline parse vs the extracted helper over the whole existing test corpus plus fixed edge inputs.

    Also the call site: `_eligible_for_removal` at base and at the head, for every corpus string as `negative_since`
    on the injected clock (so the answer cannot depend on when it is run).
    """
    old = {}
    exec("from datetime import datetime, timezone\n" + old_inline, old)
    new = {}
    exec("from datetime import datetime, timezone\nfrom typing import Any, Optional\n" + new_helper_text, new)
    files, strings = test_corpus(tests_dir)
    rows = []
    for v in EDGE_INPUTS:
        o = old["old_parse"](v); n = new["_parse_utc"](v)
        rows.append({"input": repr(v), "old": None if o is None else o.isoformat(), "new": None if n is None else n.isoformat(), "same": (o == n)})
    corpus_inputs = strings + [v for v in EDGE_INPUTS if not isinstance(v, str)]
    mismatches, parsed = [], 0
    for v in corpus_inputs:
        o = old["old_parse"](v); n = new["_parse_utc"](v)
        parsed += o is not None
        if not (o == n and (o is None) == (n is None)):
            mismatches.append(repr(v)[:80])
    digest = hashlib.sha256(json.dumps([repr(v) for v in corpus_inputs], sort_keys=True).encode()).hexdigest()
    out = {"rows": rows, "allSame": all(r["same"] for r in rows),
           "corpus": {"source": "every string literal (ast) in every .py file under tests/ at the base commit, plus the edge inputs above that are not strings",
                      "files": len(files), "inputs": len(corpus_inputs), "parseable": parsed, "unparseable": len(corpus_inputs) - parsed,
                      "mismatches": mismatches, "allSame": not mismatches, "inputsSha256": digest}}
    if removal_base is not None:
        set_clock(T0)
        b, h = both(removal_base, removal_head)
        diffs = []
        for v in corpus_inputs:
            ev = lambda su: su._eligible_for_removal(5, su.DropEvidence(tmc=False, probe=False, negative_since=v), T0)
            if ev(b) != ev(h):
                diffs.append(repr(v)[:80])
        out["callSite"] = {"what": "_eligible_for_removal(5, DropEvidence(negative_since=<input>), now=T0), base vs head", "inputs": len(corpus_inputs), "differences": diffs, "allSame": not diffs}
    return out
