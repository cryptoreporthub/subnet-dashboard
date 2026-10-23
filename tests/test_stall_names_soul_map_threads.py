import threading
import time

from internal.council import stage_trace
from internal.store import soul_map_io


def test_a_thread_holding_the_soul_map_is_named_in_the_stall(tmp_path):
    soul_path = str(tmp_path / "soul_map.json")
    inside = threading.Event()
    release = threading.Event()

    def mutate(blob):
        inside.set()
        release.wait(timeout=10)

    holder = threading.Thread(
        target=soul_map_io.write_soul_map,
        args=(mutate,),
        kwargs={"path": soul_path},
        name="liveness-writer",
    )
    holder.start()
    try:
        assert inside.wait(timeout=5)
        stall = stage_trace.describe_stall(stage_trace.StageTrace())
    finally:
        release.set()
        holder.join(timeout=10)

    assert "soul_map_io.py" in stall
    assert "write_soul_map" in stall
    assert "liveness-writer" in stall


def test_every_thread_inside_the_soul_map_is_named_not_just_the_first_few(tmp_path):
    soul_path = str(tmp_path / "soul_map.json")
    inside = threading.Event()
    release = threading.Event()

    def mutate(blob):
        inside.set()
        release.wait(timeout=10)

    holder = threading.Thread(
        target=soul_map_io.write_soul_map,
        args=(mutate,),
        kwargs={"path": soul_path},
        name="soul-map-holder",
    )
    holder.start()
    assert inside.wait(timeout=5)
    waiters = [
        threading.Thread(
            target=soul_map_io.read_soul_map, args=(soul_path,), name=f"soul-map-waiter-{i}"
        )
        for i in range(6)
    ]
    for waiter in waiters:
        waiter.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(stage_trace.soul_map_threads()) < 7:
            time.sleep(0.01)
        stall = stage_trace.describe_stall(stage_trace.StageTrace())
    finally:
        release.set()
        holder.join(timeout=10)
        for waiter in waiters:
            waiter.join(timeout=10)

    for name in ["soul-map-holder"] + [f"soul-map-waiter-{i}" for i in range(6)]:
        assert name in stall


def test_a_stall_without_soul_map_threads_does_not_mention_them():
    stall = stage_trace.describe_stall(stage_trace.StageTrace())

    assert "soul_map_io" not in stall
