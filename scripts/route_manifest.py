"""Route manifest for the server.py refactor (docs/server-refactor-plan.md, R0).

Usage: PYTHONPATH=. python scripts/route_manifest.py --print
       PYTHONPATH=. python scripts/route_manifest.py --write tests/fixtures/route_manifest.json
The manifest holds every method and path the app serves, the middleware order, and the mounts.
A move PR must leave it unchanged.
"""
import json
import sys


def build_manifest():
    import server

    app = server.app
    routes, mounts = [], []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        if methods:
            routes.extend([method, route.path] for method in methods)
        else:
            mounts.append(route.path)
    return {
        "routes": sorted(routes),
        "mounts": sorted(mounts),
        "middleware": [m.cls.__name__ for m in app.user_middleware],
    }


if __name__ == "__main__":
    manifest = build_manifest()
    if "--write" in sys.argv:
        with open(sys.argv[sys.argv.index("--write") + 1], "w") as handle:
            json.dump(manifest, handle, indent=1)
            handle.write("\n")
    else:
        print(json.dumps(manifest, indent=1))
