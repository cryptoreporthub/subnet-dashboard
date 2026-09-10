from internal.subnets.summary import summarize_subnets

def test_summary_uses_rows_and_excludes_root_explicitly():
    rows = [{"netuid": 0, "name": "Root", "status": "active"}] + [
        {"netuid": n, "status": "active"} for n in range(1, 129)
    ]
    summary = summarize_subnets(rows)
    assert summary["total_subnets"] == 129
    assert summary["active_count"] == 129
    assert summary["active_count_excluding_root"] == 128
    assert summary["root_present"] is True
    assert summary["root_netuid"] == 0

def test_summary_does_not_inherit_stale_registry_count():
    rows = [{"netuid": n, "status": "active"} for n in range(129)]
    assert summarize_subnets(rows)["total_subnets"] == 129
    assert summarize_subnets(rows)["active_count_excluding_root"] == 128

def test_summary_preserves_real_empty_state():
    summary = summarize_subnets([])
    assert summary["total_subnets"] == 0
    assert summary["active_count"] == 0
    assert summary["active_count_excluding_root"] == 0
    assert summary["root_present"] is False
