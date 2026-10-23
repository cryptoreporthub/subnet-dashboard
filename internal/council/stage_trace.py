import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKER_THREAD_PREFIXES = ("daily-pick-work", "dpick-score")
_MAX_FRAME_LABELS = 4
_SOUL_MAP_IO_MODULE = "internal.store.soul_map_io"


class StageTrace:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done: Dict[str, float] = {}
        self._running: Dict[str, float] = {}

    def enter(self, name: str) -> None:
        with self._lock:
            self._running[name] = time.monotonic()

    def leave(self, name: str) -> None:
        with self._lock:
            started = self._running.pop(name, None)
            if started is not None:
                self._done[name] = self._done.get(name, 0.0) + time.monotonic() - started

    def report(self) -> Dict[str, Dict[str, float]]:
        now = time.monotonic()
        with self._lock:
            return {
                "done": {name: round(secs, 3) for name, secs in self._done.items()},
                "running": {name: round(now - t, 3) for name, t in self._running.items()},
            }


_active: Optional[StageTrace] = None


def begin() -> StageTrace:
    global _active
    _active = StageTrace()
    return _active


@contextmanager
def stage(name: str) -> Iterator[None]:
    trace = _active
    if trace is None:
        yield
        return
    trace.enter(name)
    try:
        yield
    finally:
        trace.leave(name)


def _frame_label(frame: Any) -> str:
    leaf = frame
    app = None
    cursor = frame
    while cursor is not None:
        if app is None and os.path.abspath(cursor.f_code.co_filename).startswith(_ROOT + os.sep):
            app = cursor
        cursor = cursor.f_back
    anchor = app or leaf
    path = os.path.abspath(anchor.f_code.co_filename)
    rel = os.path.relpath(path, _ROOT) if path.startswith(_ROOT + os.sep) else os.path.basename(path)
    label = f"{rel}:{anchor.f_lineno} {anchor.f_code.co_name}"
    if anchor is not leaf:
        label += f" via {os.path.basename(leaf.f_code.co_filename)}:{leaf.f_code.co_name}"
    return label


def worker_frames() -> List[str]:
    frames = sys._current_frames()
    counts: Dict[str, int] = {}
    for thread in threading.enumerate():
        if not thread.name.startswith(_WORKER_THREAD_PREFIXES):
            continue
        frame = frames.get(thread.ident)
        if frame is not None:
            label = _frame_label(frame)
            counts[label] = counts.get(label, 0) + 1
    labels = [f"{label} x{n}" if n > 1 else label for label, n in counts.items()]
    return labels[:_MAX_FRAME_LABELS]


def soul_map_threads() -> List[str]:
    frames = sys._current_frames()
    labels: List[str] = []
    for thread in threading.enumerate():
        cursor = frames.get(thread.ident)
        while cursor is not None and cursor.f_globals.get("__name__") != _SOUL_MAP_IO_MODULE:
            cursor = cursor.f_back
        if cursor is None:
            continue
        outer = cursor.f_back
        while outer is not None and outer.f_globals.get("__name__") == _SOUL_MAP_IO_MODULE:
            outer = outer.f_back
        caller = f" from {_frame_label(outer)}" if outer is not None else ""
        labels.append(f"{thread.name} in soul_map_io.py:{cursor.f_lineno} {cursor.f_code.co_name}{caller}")
    return labels


def describe_stall(trace: StageTrace) -> str:
    running = ",".join(trace.report()["running"]) or "none"
    stall = f"stage={running} at {'; '.join(worker_frames()) or 'no worker frames'}"
    soul_map = soul_map_threads()
    if soul_map:
        stall += f" | soul_map: {'; '.join(soul_map)}"
    return stall
