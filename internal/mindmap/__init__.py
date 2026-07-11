"""Interactive Mindmap graph model (Phase G Agent A)."""

from internal.mindmap.graph import get_mindmap_graph

__all__ = ["get_mindmap_graph"]

try:
    from internal.mindmap.routes import mindmap_graph_router
except ImportError:
    mindmap_graph_router = None  # type: ignore[misc, assignment]

if mindmap_graph_router is not None:
    __all__.append("mindmap_graph_router")
