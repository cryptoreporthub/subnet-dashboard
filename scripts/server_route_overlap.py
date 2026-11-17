"""Route overlap check for docs/server-refactor-plan.md (Appendix A).

Usage: PYTHONPATH=. python scripts/server_route_overlap.py
Prints every pair of routes that can match the same request.
"""
import re, server
from starlette.routing import Match
from fastapi.routing import APIRoute
routes = [r for r in server.app.routes if isinstance(r, APIRoute)]
def sample(path):
    return re.sub(r"\{[^}:]+(:[^}]+)?\}", "1", path)
pairs = []
for i, a in enumerate(routes):
    for m in a.methods:
        scope = {"type": "http", "path": sample(a.path), "method": m}
        for j, b in enumerate(routes):
            if i == j: continue
            if b.matches(scope)[0] == Match.FULL:
                pairs.append((i, j, m, a.path, a.endpoint.__module__, b.path, b.endpoint.__module__))
srv = [p for p in pairs if "server" in (p[4], p[6])]
print("OVERLAP api routes:", len(routes), "| overlapping ordered pairs:", len(pairs), "| involving a server.py route:", len(srv))
for p in srv: print("OVERLAP", p[2], p[3], f"[{p[4]} #{p[0]}]", "also matched by", p[5], f"[{p[6]} #{p[1]}]")
dups = {}
for r in routes:
    for m in r.methods: dups.setdefault((m, r.path), []).append(r.endpoint.__module__)
print("OVERLAP exact duplicate method+path:", {k: v for k, v in dups.items() if len(v) > 1})
print("JINJA undefined:", type(server.templates.env.undefined).__name__ if not isinstance(server.templates.env.undefined, type) else server.templates.env.undefined.__name__)
