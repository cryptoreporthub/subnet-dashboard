import pytest

from internal.chain_price import membership
from internal.chain_price.membership import read_chain_membership
from internal.chain_read import ChainRead

HASH = "0x" + "ab" * 32


class FakeReader:
    def __init__(self, head):
        self._head = head

    def pin_finalized_head(self):
        return self._head

    def call_fn(self):
        return lambda method, params: (None, "ok")


def _good():
    return {"block_hash": HASH, "netuids": [1, 2, 5, 200]}


def test_parse_accepts_a_canonical_read_and_round_trips():
    chain = ChainRead.parse(_good())
    assert chain == ChainRead(HASH, (1, 2, 5, 200))
    assert ChainRead.parse(chain.to_dict()) == chain


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(block_hash="0xabc"),
        lambda d: d.update(block_hash=HASH.upper().replace("0X", "0x")),
        lambda d: d.update(block_hash=None),
        lambda d: d.update(block_hash=12),
        lambda d: d.pop("block_hash"),
        lambda d: d.update(netuids=[]),
        lambda d: d.update(netuids=None),
        lambda d: d.update(netuids="12"),
        lambda d: d.update(netuids=[1, 1, 2]),
        lambda d: d.update(netuids=[2, 1]),
        lambda d: d.update(netuids=[0, 1]),
        lambda d: d.update(netuids=[-1, 1]),
        lambda d: d.update(netuids=[1, 65536]),
        lambda d: d.update(netuids=[1, True]),
        lambda d: d.update(netuids=[1, "2"]),
        lambda d: d.update(netuids=[1, 2.0]),
        lambda d: d.update(netuids=[1, None]),
        lambda d: d.pop("netuids"),
    ],
)
def test_parse_rejects_without_raising(mutate):
    raw = _good()
    mutate(raw)
    assert ChainRead.parse(raw) is None


@pytest.mark.parametrize("raw", [None, [], "x", 3, [1, 2]])
def test_parse_rejects_a_non_dict(raw):
    assert ChainRead.parse(raw) is None


def test_read_chain_membership_pins_the_head_and_returns_the_set(monkeypatch):
    monkeypatch.setattr(membership, "get_member_netuids", lambda call, at_hash: ([1, 2, 3], "ok"))
    chain, outcome = read_chain_membership(FakeReader((HASH.upper().replace("0X", "0x"), "ok")))
    assert outcome == "ok"
    assert chain == ChainRead(HASH, (1, 2, 3))


def test_read_chain_membership_reports_a_failed_pin(monkeypatch):
    monkeypatch.setattr(membership, "get_member_netuids", lambda *a: pytest.fail("must not read"))
    chain, outcome = read_chain_membership(FakeReader((None, "rpc_error")))
    assert chain is None
    assert outcome == "rpc_error"


def test_read_chain_membership_reports_a_failed_read(monkeypatch):
    monkeypatch.setattr(membership, "get_member_netuids", lambda call, at_hash: ([], "invalid"))
    chain, outcome = read_chain_membership(FakeReader((HASH, "ok")))
    assert chain is None
    assert outcome == "invalid"


def test_read_chain_membership_never_returns_an_empty_set(monkeypatch):
    monkeypatch.setattr(membership, "get_member_netuids", lambda call, at_hash: ([], "ok"))
    chain, outcome = read_chain_membership(FakeReader((HASH, "ok")))
    assert chain is None
    assert outcome != "ok"


def test_recorded_chain_membership_parses_to_a_chain_read_without_root():
    import json
    from pathlib import Path

    from internal.chain_price.membership import read_chain_membership

    data = json.loads((Path(__file__).parent / "fixtures" / "chain" / "bm_9280796.json").read_text())
    block_hash = "0x72a82add74d481216a2f4b8f77e7729f88b2abf0654a9c6be89a3cf10f7cedd0"

    class _Reader:
        def pin_finalized_head(self):
            return block_hash, "ok"

        def call_fn(self):
            def call(method, params=None):
                return data[f"{method}|{json.dumps(params or [])}"], "ok"

            return call

    chain, outcome = read_chain_membership(_Reader())

    assert outcome == "ok"
    assert chain is not None
    assert chain.block_hash == block_hash
    assert 0 not in chain.netuids
    assert len(chain.netuids) > 50
