import requests


def test_probe_fetch_timeout_is_unobserved(monkeypatch):
    from internal.subnet_universe import _default_probe_fetch

    class _Client:
        def get_alpha_price_probed(self, netuid):
            return None, "timeout"

    monkeypatch.setattr("internal.chain_client.get_default_client", lambda: _Client())
    observed, complete = _default_probe_fetch([5])
    assert observed[5] is None
    assert complete is True


def test_probe_fetch_read_timeout_via_requests(monkeypatch):
    from internal.chain_client import ChainClient
    from internal.subnet_universe import _default_probe_fetch

    client = ChainClient("https://probe.example", init_volume_db=False, retries=0)

    def _boom(*_a, **_k):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(client, "_call", _boom)
    monkeypatch.setattr("internal.chain_client.get_default_client", lambda: client)
    observed, _complete = _default_probe_fetch([7])
    assert observed[7] is None
