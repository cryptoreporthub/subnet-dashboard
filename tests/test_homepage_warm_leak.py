"""A hung homepage render must not spawn a second homepage-warm-render thread."""

import threading

import server


def test_hung_homepage_render_refuses_second_thread(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def hang(_request):
        started.set()
        assert release.wait(timeout=5)
        return "<html>tribunal-hero</html>"

    monkeypatch.setattr(server, "_render_index_html", hang)
    # warm_timeout = HOMEPAGE_BUILD_TIMEOUT + 5.0
    monkeypatch.setattr(server, "HOMEPAGE_BUILD_TIMEOUT", -4.95)
    server._HOMEPAGE_HTML_CACHE["html"] = None
    server._HOMEPAGE_HTML_CACHE["at"] = 0.0
    server._HOMEPAGE_WARMING = False
    server._HOMEPAGE_RENDER_THREAD = None

    server._warm_homepage_cache()
    assert started.wait(timeout=2)
    server._warm_homepage_cache()
    server._warm_homepage_cache()

    render_threads = [
        th for th in threading.enumerate() if th.name == "homepage-warm-render"
    ]
    assert len(render_threads) == 1
    assert server._HOMEPAGE_WARMING is True

    release.set()
    render_threads[0].join(timeout=2)
    assert render_threads[0].is_alive() is False
    assert server._HOMEPAGE_WARMING is False
