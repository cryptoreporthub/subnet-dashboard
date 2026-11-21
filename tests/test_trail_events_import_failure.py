"""emit_trail_event must not raise when the mindmap bridge cannot be imported."""

import sys

from internal.learning import trail_events


def test_emit_trail_event_does_not_raise_when_bridge_import_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "internal.council.mindmap_bridge", None)

    assert trail_events.emit_trail_event("test_event", netuid=1) is None
