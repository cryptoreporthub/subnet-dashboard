"""Per-build cost counters: conviction queries, RPC attempts, CPU, and the build window."""

import pytest

from internal import build_cost


@pytest.fixture(autouse=True)
def _no_active_build():
    build_cost.end()
    yield
    build_cost.end()


def test_record_is_a_noop_without_an_active_build():
    build_cost.record("conviction", 0.5)
    build_cost.record("rpc", 0.5)
    assert build_cost.end() == {}


def test_window_counts_each_kind_and_resets_on_end():
    build_cost.begin("build-1")
    build_cost.record("conviction", 0.25)
    build_cost.record("conviction", 0.75)
    build_cost.record("rpc", 0.5)
    cost = build_cost.end()
    assert cost["build_id"] == "build-1"
    assert cost["conviction_queries"] == 2
    assert cost["conviction_query_seconds"] == 1.0
    assert cost["rpc_calls"] == 1
    assert cost["rpc_seconds"] == 0.5
    assert cost["wall_seconds"] >= 0.0
    assert cost["process_cpu_seconds"] >= 0.0
    build_cost.record("rpc", 1.0)
    assert build_cost.end() == {}


def test_begin_discards_a_window_left_open_by_a_failed_build():
    build_cost.begin("failed")
    build_cost.record("rpc", 1.0)
    build_cost.begin("next")
    assert build_cost.end()["rpc_calls"] == 0


def test_timed_post_records_success_and_failure(monkeypatch):
    from internal import chain_client

    class _Resp:
        status_code = 200

    def _ok(*args, **kwargs):
        return _Resp()

    def _boom(*args, **kwargs):
        raise chain_client.requests.Timeout("slow")

    build_cost.begin("rpc-build")
    monkeypatch.setattr(chain_client.requests, "post", _ok)
    assert chain_client._timed_post("http://x", {}, 1.0).status_code == 200
    monkeypatch.setattr(chain_client.requests, "post", _boom)
    with pytest.raises(chain_client.requests.Timeout):
        chain_client._timed_post("http://x", {}, 1.0)
    cost = build_cost.end()
    assert cost["rpc_calls"] == 2


def test_conviction_rows_counts_one_query_per_call():
    from internal.message_intel import rollup

    class _Cursor:
        def fetchall(self):
            return []

    class _Conn:
        def execute(self, *args, **kwargs):
            return _Cursor()

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *exc):
            return False

    class _Db:
        def _connection(self):
            return _Ctx()

    build_cost.begin("conviction-build")
    rollup._conviction_rows(db=_Db())
    rollup._conviction_rows(db=_Db())
    assert build_cost.end()["conviction_queries"] == 2
