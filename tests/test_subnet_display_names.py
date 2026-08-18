"""Tests for display_name_for_netuid and pump desk feed."""

from unittest.mock import patch

from internal.subnet_names import display_name_for_netuid, is_generic_display_name
from internal.subnets.feed import load_subnets_for_display


def test_display_name_prefers_specific_ladder_hint(monkeypatch):
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: {54: "Yanez"})
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    name = display_name_for_netuid(
        54,
        subnet_row={"netuid": 54, "name": "WebGenieAI"},
        ladder_hint="Yanez MIID",
        use_taostats_fallback=False,
    )
    assert name == "Yanez MIID"


def test_is_generic_display_name():
    assert is_generic_display_name("SN78", 78)
    assert is_generic_display_name("Unknown", 78)
    assert not is_generic_display_name("Loosh", 78)


def test_display_name_tmc_sn6_numinous(monkeypatch):
    monkeypatch.setattr(
        "internal.subnet_names._tmc_display_names",
        lambda: {6: "Numinous"},
    )
    monkeypatch.setattr(
        "internal.subnet_names._remote_registry",
        lambda: {"6": {"name": "Infinite Games"}},
    )
    name = display_name_for_netuid(6, use_taostats_fallback=False)
    assert name == "Numinous"


def test_display_name_override_sn39_deprecated(monkeypatch):
    """SN39 on-chain identity is deprecated; stale taostat still lists EdgeMaxxing."""
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: {})
    monkeypatch.setattr(
        "internal.subnet_names._load_name_overrides",
        lambda: {"39": "SN39 (deprecated)"},
    )
    monkeypatch.setattr(
        "internal.subnet_names._remote_registry",
        lambda: {"39": {"name": "EdgeMaxxing"}},
    )
    monkeypatch.setattr(
        "internal.subnet_names._load_local_registry",
        lambda: {"39": {"name": "EdgeMaxxing"}},
    )
    name = display_name_for_netuid(39, use_taostats_fallback=False)
    assert name == "SN39 (deprecated)"


def test_display_name_override_sn6_numinous_when_tmc_empty(monkeypatch):
    """Curator override wins over stale registry when TMC is empty."""
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: {})
    monkeypatch.setattr(
        "internal.subnet_names._remote_registry",
        lambda: {"6": {"name": "Infinite Games"}},
    )
    monkeypatch.setattr(
        "internal.subnet_names._load_local_registry",
        lambda: {"6": {"name": "Infinite Games"}},
    )
    name = display_name_for_netuid(6, use_taostats_fallback=False)
    assert name == "Numinous"


def test_display_name_tmc_sn16_fast_thinker(monkeypatch):
    monkeypatch.setattr(
        "internal.subnet_names._tmc_display_names",
        lambda: {16: "Fast Thinker"},
    )
    name = display_name_for_netuid(16, use_taostats_fallback=False)
    assert name == "Fast Thinker"


def test_display_name_tmc_sn23_trishool(monkeypatch):
    monkeypatch.setattr(
        "internal.subnet_names._tmc_display_names",
        lambda: {23: "Trishool"},
    )
    name = display_name_for_netuid(23, use_taostats_fallback=False)
    assert name == "Trishool"


def test_display_name_prefers_enriched_row(monkeypatch):
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    row = {"netuid": 40, "name": "Chunking", "source": "taomarketcap"}
    name = display_name_for_netuid(40, subnet_row=row, use_taostats_fallback=False)
    assert name == "Chunking"


def test_display_name_skips_stale_tmc_ralph(monkeypatch):
    """With no override, a stale row name is skipped, not surfaced."""
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: {})
    name = display_name_for_netuid(
        40,
        subnet_row={"netuid": 40, "name": "Ralph", "source": "registry"},
        ladder_hint="Ralph",
        use_taostats_fallback=False,
    )
    assert name != "Ralph"
    assert name == "Chunking" or name == "SN40"


def test_display_name_override_wins_over_trustworthy_live(monkeypatch):
    """A deliberate override beats a 'trustworthy' live feed name (Blockmachine/TMC).

    Regression for the live hero label flipping back off the curated name when the
    source is live rather than degraded/snapshot.
    """
    monkeypatch.setattr(
        "internal.subnet_names._load_name_overrides",
        lambda: {"40": "ralph"},
    )
    name = display_name_for_netuid(
        40,
        subnet_row={"netuid": 40, "name": "Chunking", "source": "blockmachine"},
        use_taostats_fallback=False,
    )
    assert name == "ralph"


def test_canonical_display_override_wins(monkeypatch):
    """Override also wins via canonical display used by picks/horizon enrichment."""
    monkeypatch.setattr(
        "internal.subnet_names._load_name_overrides",
        lambda: {"40": "ralph"},
    )
    from internal.subnet_names import canonical_subnet_display

    out = canonical_subnet_display({"netuid": 40, "name": "Chunking"})
    assert out["name"] == "ralph"


def test_load_subnets_for_display_uses_council_feed(monkeypatch):
    monkeypatch.setattr(
        "internal.subnets.feed.get_council_subnet_feed",
        lambda timeout=None: ([{"netuid": 16, "name": "BitKoop", "source": "taomarketcap"}], "taomarketcap"),
    )
    rows = load_subnets_for_display()
    assert rows[0]["name"] == "BitKoop"


def test_resolve_subnet_name_uses_tmc_when_registry_unknown(monkeypatch):
    monkeypatch.setattr(
        "internal.subnet_names._load_local_registry",
        lambda: {"93": {"name": "Unknown"}},
    )
    monkeypatch.setattr("internal.subnet_names._remote_registry", lambda: {})
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    monkeypatch.setattr(
        "internal.subnet_names._tmc_display_names",
        lambda: {93: "Bitcast"},
    )
    from internal.subnet_names import resolve_subnet_name

    assert resolve_subnet_name(93, use_taostats=False) == "Bitcast"


def test_load_subnets_for_display_registry_fallback(monkeypatch):
    monkeypatch.setattr(
        "internal.subnets.feed.get_council_subnet_feed",
        lambda timeout=None: ([], "none"),
    )
    with patch("internal.subnet_names.enrich_subnet_rows") as enrich:
        enrich.return_value = [{"netuid": 1, "name": "Alpha"}]
        rows = load_subnets_for_display()
    assert rows[0]["name"] == "Alpha"
