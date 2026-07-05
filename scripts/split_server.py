#!/usr/bin/env python3
"""Split server.py FastAPI monolith into a modular server/ package."""
import os, re, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "server.py"
SERVER_PKG = REPO_ROOT / "server"
ROUTES_DIR = SERVER_PKG / "routes"
SERVICES_DIR = SERVER_PKG / "services"

ROUTE_MAP = [
    (r"^(/|/health|/api/health|/favicon)", "system"),
    (r"^/api/subnets", "subnets"),
    (r"^/api/judges|^/api/council|^/api/paper-portfolio|^/api/postmortems", "judges"),
    (r"^/api/simivision", "simivision"),
    (r"^/api/indicators", "indicators"),
    (r"^/api/mindmap", "mindmap"),
    (r"^/api/learning", "learning"),
    (r"^/api/pump-analytics", "pumps"),
    (r"^/api/rotation-tokens", "tokens"),
]

def read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()

def is_route_decorator(ln):
    return bool(re.match(r'^\s*@app\.(get|post|put|delete|patch|api_route)\(', ln))

def is_top_level_def_or_deco(ln):
    """True if line starts at column 0 with def, class, or @."""
    if ln[0:1] not in (' ', '\t', '\n', '\r') and ln.strip():
        if re.match(r'^(def |class |@)', ln.strip()):
            return True
    return False

def extract_route_blocks(lines):
    """Parse into (header, route_blocks, tail)."""
    n = len(lines)
    # Find first route decorator
    first_route = None
    for i in range(n):
        if is_route_decorator(lines[i]):
            first_route = i
            break
    if first_route is None:
        print("WARNING: No route decorators found!")
        return lines, [], []

    header_lines = lines[:first_route]
    route_blocks = []
    i = first_route

    while i < n:
        if not is_route_decorator(lines[i]):
            i += 1
            continue

        # Collect all decorator lines above the function
        deco_start = i
        deco_indices = [i]
        i += 1
        while i < n:
            stripped = lines[i].strip()
            if stripped.startswith('@'):
                deco_indices.append(i)
                i += 1
            elif stripped.startswith('async def ') or stripped.startswith('def '):
                break
            elif stripped == '' or stripped.startswith('#'):
                i += 1
            else:
                # Something else — not a clean decorator→def pair, skip
                break

        if i >= n:
            break

        stripped = lines[i].strip()
        if not (stripped.startswith('async def ') or stripped.startswith('def ')):
            # Decorator not followed by function def — skip
            continue

        # Extract function body
        func_start = i
        base_indent = len(lines[i]) - len(lines[i].lstrip())
        i += 1
        while i < n:
            stripped2 = lines[i].strip()
            if stripped2:
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent <= base_indent:
                    break
            i += 1
        func_end = i

        # Extract URL path
        first_deco = lines[deco_indices[0]]
        url_match = re.search(r"""['"](/[^'"]*)""", first_deco)
        url_path = url_match.group(1) if url_match else "unknown"

        route_blocks.append({
            "url_path": url_path,
            "lines": lines[deco_indices[0]:func_end]
        })

    last_end = route_blocks[-1]["end"] if hasattr(route_blocks[-1], 'end') else 0
    # Actually, compute last_end from the last block's lines relative to original
    if route_blocks:
        # Find the max line index used
        tail_start = 0
        for b in route_blocks:
            start_in_original = None
            # Search for the block's first line in the original
            first_line = b["lines"][0]
            for idx, orig_line in enumerate(lines):
                if orig_line == first_line:
                    end_idx = idx + len(b["lines"])
                    if end_idx > tail_start:
                        tail_start = end_idx
                    break
        tail_lines = lines[tail_start:]
    else:
        tail_lines = []

    # Also collect any non-route top-level code between routes as "core" 
    return header_lines, route_blocks, tail_lines

def group_routes(route_blocks):
    groups = {}
    for block in route_blocks:
        url = block["url_path"]
        module = "web"
        for pattern, mod in ROUTE_MAP:
            if re.match(pattern, url):
                module = mod
                break
        groups.setdefault(module, []).append(block)
    return groups

def extract_imports(header_lines):
    """Get all import lines from header."""
    imports = []
    for line in header_lines:
        s = line.strip()
        if re.match(r'^(import |from )', s):
            imports.append(line)
    return imports

def write_route_module(name, routes, all_imports):
    path = ROUTES_DIR / f"{name}.py"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'"""Routes: {name} — {len(routes)} endpoint(s)."""\n')
        f.write('from fastapi import APIRouter\n')
        for imp in all_imports:
            f.write(imp)
        f.write('\nrouter = APIRouter()\n\n')
        for block in routes:
            for line in block["lines"]:
                fixed = line
                for m in ['get', 'post', 'put', 'delete', 'patch', 'api_route']:
                    fixed = fixed.replace(f'@app.{m}(', f'@router.{m}(')
                f.write(fixed)
            f.write('\n')

def main():
    print("Reading server.py...")
    lines = read_lines(SERVER_PY)
    print(f"  {len(lines)} lines")

    header, routes, tail = extract_route_blocks(lines)
    print(f"  Header: {len(header)} lines")
    print(f"  Routes: {len(routes)}")
    print(f"  Tail: {len(tail)} lines")

    all_imports = extract_imports(header)
    groups = group_routes(routes)
    for mod, blocks in sorted(groups.items()):
        print(f"  {mod}: {len(blocks)} route(s)")

    # Create directories
    SERVER_PKG.mkdir(exist_ok=True)
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)

    # server/config.py — all the header content
    with open(SERVER_PKG / "config.py", "w", encoding="utf-8") as f:
        f.write('"""Server configuration — constants, env vars, data seeding."""\n')
        for line in header:
            f.write(line)

    # server/state.py — empty placeholder (global state extracted later manually)
    with open(SERVER_PKG / "state.py", "w", encoding="utf-8") as f:
        f.write('"""Global state (caches, locks, timestamps) — extracted from config.py."""\n')

    # server/routes/__init__.py
    with open(ROUTES_DIR / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Route registration."""\n')
        f.write('def register_routes(app):\n')
        for mod in sorted(groups.keys()):
            f.write(f'    from server.routes.{mod} import router as {mod}_router\n')
            f.write(f'    app.include_router({mod}_router)\n')

    # server/services/__init__.py
    with open(SERVICES_DIR / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Background services."""\n')

    # Write each route module
    for mod_name, mod_routes in groups.items():
        print(f"Writing {mod_name}.py ({len(mod_routes)} routes)...")
        write_route_module(mod_name, mod_routes, all_imports)

    # server/__init__.py — app factory from tail
    with open(SERVER_PKG / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Subnet Dashboard server package."""\n')
        f.write('from fastapi import FastAPI\n')
        f.write('from fastapi.middleware.cors import CORSMiddleware\n')
        f.write('from fastapi.staticfiles import StaticFiles\n')
        f.write('from fastapi.templating import Jinja2Templates\n')
        f.write('import os\n\n')
        f.write('def create_app():\n')
        f.write('    app = FastAPI()\n')
        f.write('    # CORS\n')
        f.write('    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])\n')
        f.write('    # Static files\n')
        f.write('    app.mount("/static", StaticFiles(directory="static"), name="static")\n')
        f.write('    # Register routes\n')
        f.write('    from server.routes import register_routes\n')
        f.write('    register_routes(app)\n')
        f.write('    return app\n')

    # Replace server.py with shim
    shim = '"""Subnet Dashboard — modular entry point."""\nimport os\nfrom server import create_app\napp = create_app()\n\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))\n'
    with open(SERVER_PY, "w", encoding="utf-8") as f:
        f.write(shim)

    # Remove old wrappers
    for old in ["judge_app.py", "council_app.py"]:
        p = REPO_ROOT / old
        if p.exists():
            p.unlink()
            print(f"Removed {old}")

    print("\nDone. Commit and push to deploy.")

if __name__ == "__main__":
    main()
