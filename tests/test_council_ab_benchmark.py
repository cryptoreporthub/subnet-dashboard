from datetime import datetime, timedelta, timezone


def _subnet(netuid, price=10.0):
    return {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "price": price,
        "volume": 100000,
        "status": "active",
    }


def test_record_snapshot_keeps_daily_and_judge_top_five_in_one_universe(tmp_path, monkeypatch):
    from internal.council import ab_benchmark

    daily_scores = {1: 91, 2: 90, 3: 89, 4: 88, 5: 87, 6: 86}
    judge_scores = {1: 0.61, 2: 0.99, 3: 0.88, 4: 0.77, 5: 0.66, 6: 0.55}

    def fake_day(row, _ctx):
        return {"total_score": daily_scores[row["netuid"]], "confidence": 0.6}

    def fake_judges(rows, market_context=None, use_chain=False):
        return [
            {
                "netuid": row["netuid"],
                "name": row["name"],
                "consensus": {
                    "score": judge_scores[row["netuid"]],
                    "agreement": 0.9,
                    "confidence": 0.8,
                    "verdict": "long",
                },
            }
            for row in sorted(rows, key=lambda item: judge_scores[item["netuid"]], reverse=True)
        ]

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day", fake_day
    )
    monkeypatch.setattr("internal.judges.subnet_judges.score_all_subnets", fake_judges)
    path = str(tmp_path / "ab.json")
    snap = ab_benchmark.record_snapshot(
        [_subnet(n) for n in range(1, 7)],
        {},
        captured_at="2026-08-15T00:15:00Z",
        path=path,
    )

    assert [row["netuid"] for row in snap["daily_model"]] == [1, 2, 3, 4, 5]
    assert [row["netuid"] for row in snap["judge_council"]] == [2, 3, 4, 5, 1]
    assert snap["universe_count"] == 6

    same_day = ab_benchmark.record_snapshot(
        [_subnet(n) for n in range(1, 7)],
        {},
        captured_at="2026-08-15T12:00:00Z",
        path=path,
    )
    assert same_day["universe_count"] == 6
    assert same_day["observation_slot"] != snap["observation_slot"]
    assert len(ab_benchmark._load(path)["snapshots"]) == 2


def test_settle_due_snapshots_grades_long_short_and_neutral(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=25)
    captured_iso = captured.isoformat().replace("+00:00", "Z")
    ab_benchmark.record_snapshot(
        [_subnet(1, 10), _subnet(2, 10), _subnet(3, 10)],
        {},
        captured_at=captured_iso,
        path=path,
    )

    data = ab_benchmark._load(path)
    data["snapshots"][0]["daily_model"] = [
        {"netuid": 1, "direction": "long", "entry_price": 10, "result": None}
    ]
    data["snapshots"][0]["judge_council"] = [
        {"netuid": 2, "direction": "short", "entry_price": 10, "result": None},
        {"netuid": 3, "direction": "neutral", "entry_price": 10, "result": None},
    ]
    ab_benchmark._save(data, path)

    settled = ab_benchmark.settle_due_snapshots(
        [_subnet(1, 12), _subnet(2, 8), _subnet(3, 14)],
        now=captured + timedelta(hours=25),
        path=path,
    )
    snap = settled["snapshots"][0]
    assert snap["daily_model"][0]["result"] == "hit"
    assert snap["judge_council"][0]["result"] == "hit"
    assert snap["judge_council"][1]["result"] == "neutral"

def _seed(path, captured, rows):
    from internal.council import ab_benchmark

    ab_benchmark.record_snapshot(
        [_subnet(1, 10), _subnet(2, 10)],
        {},
        captured_at=captured.isoformat().replace("+00:00", "Z"),
        path=path,
    )
    data = ab_benchmark._load(path)
    data["snapshots"][0]["daily_model"] = rows
    data["snapshots"][0]["judge_council"] = []
    ab_benchmark._save(data, path)



def _quote(netuid, price, live=None):
    row = _subnet(netuid, price)
    if live is not None:
        row["live"] = live
    return row


def test_registry_fallback_quote_is_deferred_until_a_live_quote_arrives(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed(path, captured, [{"netuid": 1, "direction": "long", "entry_price": 10, "result": None}])

    deferred = ab_benchmark.settle_due_snapshots(
        [_quote(1, 10, live=False)], now=captured + timedelta(hours=25), path=path
    )
    assert deferred["snapshots"][0]["daily_model"][0]["result"] is None
    assert deferred["snapshots"][0]["status"] == "partial"

    live = ab_benchmark.settle_due_snapshots(
        [_quote(1, 11, live=True)], now=captured + timedelta(hours=26), path=path
    )
    row = live["snapshots"][0]["daily_model"][0]
    assert row["result"] == "hit" and row["exit_price"] == 11
    assert live["snapshots"][0]["status"] == "settled"


def test_registry_fallback_after_grace_is_stale_and_excluded_from_hit_rate(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=60)
    _seed(
        path,
        captured,
        [
            {"netuid": 1, "direction": "long", "entry_price": 10, "result": None},
            {"netuid": 2, "direction": "long", "entry_price": 10, "result": None},
        ],
    )
    late = captured + timedelta(
        hours=ab_benchmark.AB_BENCHMARK_HORIZON_HOURS + ab_benchmark.AB_STALE_EXIT_GRACE_HOURS
    )
    ab_benchmark.settle_due_snapshots(
        [_quote(1, 10, live=False), _quote(2, 12, live=True)], now=late, path=path
    )

    rows = ab_benchmark._load(path)["snapshots"][0]["daily_model"]
    assert [r["result"] for r in rows] == ["stale", "hit"]
    assert rows[0]["exit_price"] is None and rows[0]["return_pct"] is None
    metrics = ab_benchmark.comparison(path=path)["daily_model"]
    assert metrics["stale_exit_entries"] == 1
    assert metrics["directional_entries"] == 1
    assert metrics["hit_rate"] == 1.0


def test_unchanged_live_quote_is_a_real_flat_move_and_stays_graded(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed(path, captured, [{"netuid": 1, "direction": "long", "entry_price": 10, "result": None}])

    settled = ab_benchmark.settle_due_snapshots(
        [_quote(1, 10, live=True)], now=captured + timedelta(hours=25), path=path
    )
    row = settled["snapshots"][0]["daily_model"][0]
    assert row["result"] == "miss" and row["exit_price"] == 10 and row["return_pct"] == 0.0
    metrics = ab_benchmark.comparison(path=path)["daily_model"]
    assert metrics["stale_exit_entries"] == 0
    assert metrics["directional_entries"] == 1


def test_row_without_a_live_flag_is_graded_as_before(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed(path, captured, [{"netuid": 1, "direction": "long", "entry_price": 10, "result": None}])

    settled = ab_benchmark.settle_due_snapshots(
        [_quote(1, 10)], now=captured + timedelta(hours=25), path=path
    )
    assert settled["snapshots"][0]["daily_model"][0]["result"] == "miss"


def _settled_snapshots(path, count, result):
    from internal.council import ab_benchmark

    base = datetime.now(timezone.utc) - timedelta(days=30)
    snapshots = []
    for index in range(count):
        row = {"netuid": 1, "direction": "long", "entry_price": 10, "result": result}
        snapshots.append(
            {
                "captured_at": (base + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                "date": "2026-09-01",
                "status": "settled",
                "daily_model": [dict(row)],
                "judge_council": [],
            }
        )
    ab_benchmark._save({"snapshots": snapshots}, path)


def test_stale_only_snapshots_do_not_make_the_comparison_research_ready(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    needed = ab_benchmark.comparison(path=path)["minimum_recommended_snapshots"]
    _settled_snapshots(path, needed, "stale")

    result = ab_benchmark.comparison(path=path)
    assert result["settled_observation_count"] == needed
    assert result["scored_observation_count"] == 0
    assert result["daily_model"]["stale_exit_entries"] == needed
    assert result["daily_model"]["directional_entries"] == 0
    assert result["research_ready"] is False


def test_scored_snapshots_make_the_comparison_research_ready(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    needed = ab_benchmark.comparison(path=path)["minimum_recommended_snapshots"]
    _settled_snapshots(path, needed, "hit")
    result = ab_benchmark.comparison(path=path)
    assert result["scored_observation_count"] == needed
    assert result["research_ready"] is True
