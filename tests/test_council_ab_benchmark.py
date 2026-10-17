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


def test_unchanged_exit_quote_is_deferred_not_graded_a_miss(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed(path, captured, [{"netuid": 1, "direction": "long", "entry_price": 10, "result": None}])

    stale = ab_benchmark.settle_due_snapshots(
        [_subnet(1, 10)], now=captured + timedelta(hours=25), path=path
    )
    assert stale["snapshots"][0]["daily_model"][0]["result"] is None
    assert stale["snapshots"][0]["status"] == "partial"

    fresh = ab_benchmark.settle_due_snapshots(
        [_subnet(1, 11)], now=captured + timedelta(hours=26), path=path
    )
    row = fresh["snapshots"][0]["daily_model"][0]
    assert row["result"] == "hit" and row["exit_price"] == 11
    assert fresh["snapshots"][0]["status"] == "settled"


def test_exit_quote_still_unchanged_after_grace_is_flat_and_not_in_hit_rate(tmp_path):
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
    late = captured + timedelta(hours=ab_benchmark.AB_BENCHMARK_HORIZON_HOURS + ab_benchmark.AB_STALE_EXIT_GRACE_HOURS)
    ab_benchmark.settle_due_snapshots([_subnet(1, 10), _subnet(2, 12)], now=late, path=path)

    metrics = ab_benchmark.comparison(path=path)["daily_model"]
    assert [r["result"] for r in ab_benchmark._load(path)["snapshots"][0]["daily_model"]] == ["flat", "hit"]
    assert metrics["stale_exit_entries"] == 1
    assert metrics["directional_entries"] == 1
    assert metrics["hit_rate"] == 1.0


def test_legacy_miss_graded_off_an_unchanged_quote_is_excluded_from_metrics(tmp_path):
    from internal.council import ab_benchmark

    path = str(tmp_path / "ab.json")
    captured = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed(
        path,
        captured,
        [
            {"netuid": 1, "direction": "long", "entry_price": 10, "exit_price": 10, "return_pct": 0.0, "result": "miss"},
            {"netuid": 2, "direction": "long", "entry_price": 10, "exit_price": 9, "return_pct": -10.0, "result": "miss"},
        ],
    )
    metrics = ab_benchmark.comparison(path=path)["daily_model"]
    assert metrics["stale_exit_entries"] == 1
    assert metrics["directional_entries"] == 1
    assert metrics["hit_rate"] == 0.0
