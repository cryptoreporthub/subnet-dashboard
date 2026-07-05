#!/usr/bin/env python3
"""V2: Fix route distribution — read from server/config.py + server/routes/system.py and redistribute."""
import os, re, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PKG = REPO_ROOT / "server"
ROUTES_DIR = SERVER_PKG / "routes"
CONFIG_PY = SERVER_PKG / "config.py"
SYSTEM_PY = ROUTES_DIR / "system.py"

# Most-specific-first ordering — DO NOT put a general "/" pattern here.
ROUTE_MAP = [
    (r"^/api/indicators", "indicators"),
    (r"^/api/mindmap", "mindmap"),
    (r"^/api/learning", "learning"),
    (r"^/api/pump-analytics", "pumps"),
    (r"^/api/rotation-tokens", "tokens"),
    (r"^/api/judges|^/api/council|^/api/paper-portfolio|^/api/postmortems|^/api/portfolios|^/api/oracle", "judges"),
    (r"^/api/simivision|^/api/top-pick", "simivision"),
    (r"^/api/subnets", "subnets"),
    (r"^/api/scenario-memory", "learning"),
    (r"^/api/prediction-cache", "judges"),
    (r"^/api/health$|^/health$|^/api/freshness$|^/api/pick-history$|^/api/price-tracking|^/api/resolve-predictions$|^/favicon", "system"),
]

def read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()

def is_router_decorator(ln):
    return bool(re.match(r'^\s*@router\.(get|post|put|delete|patch|api_route)\(', ln))

def extract_route_blocks(lines):
    """Parse route functions from a module file."""
    n = len(lines)
    route_blocks = []
    i = 0
    while i < n:
        if not is_router_decorator(lines[i]):
            i += 1
            continue

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
                break

        if i >= n:
            break

        stripped = lines[i].strip()
        if not (stripped.startswith('async def ') or stripped.startswith('def ')):
            continue

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

        first_deco = lines[deco_indices[0]]
        url_match = re.search(r"""['"](/[^'"]*)""", first_deco)
        url_path = url_match.group(1) if url_match else "unknown"

        route_blocks.append({
            "url_path": url_path,
            "lines": lines[deco_indices[0]:i]
        })

    return route_blocks

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

def extract_imports(lines_text):
    imports = []
    for line in lines_text:
        s = line.strip()
        if re.match(r'^(import |from )', s):
            imports.append(line)
    return imports

def main():
    print("V2: redistributing routes from server/routes/system.py...")

    # Read config.py for imports
    config_lines = read_lines(CONFIG_PY)
    system_lines = read_lines(SYSTEM_PY)
    print(f"  config.py: {len(config_lines)} lines")
    print(f"  system.py: {len(system_lines)} lines")

    # Extract import lines from config
    all_imports = list(dict.fromkeys(extract_imports(config_lines)))  # dedupe
    print(f"  imports: {len(all_imports)} unique")

    # Extract route blocks from system.py
    routes = extract_route_blocks(system_lines)
    print(f"  routes found: {len(routes)}")
    for r in routes:
        print(f"    {r['url_path']} ({len(r['lines'])} lines)")

    groups = group_routes(routes)
    print(f"\n  grouped into {len(groups)} modules:")
    for mod, blocks in sorted(groups.items()):
        print(f"    {mod}: {len(blocks)} route(s)")

    # Remove old system.py (will be rewritten)
    SYSTEM_PY.unlink()

    # Ensure dirs exist
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)

    # Write each route module
    for mod_name, mod_routes in groups.items():
        if mod_name == "system":
            path = ROUTES_DIR / f"{mod_name}.py"
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'"""Routes: {mod_name}."""\n')
                f.write('from fastapi import APIRouter, Request\n')
                f.write('from fastapi.responses import PlainTextResponse, JSONResponse\n')
                f.write('from datetime import datetime\n')
                f.write('import json, os, logging\n')
                for imp in all_imports:
                    f.write(imp)
                f.write('\nrouter = APIRouter()\n')
                f.write('logger = logging.getLogger(__name__)\n\n')
                for block in mod_routes:
                    for line in block["lines"]:
                        f.write(line)
        else:
            path = ROUTES_DIR / f"{mod_name}.py"
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'"""Routes: {mod_name}."""\n')
                f.write('from fastapi import APIRouter, Request\n')
                for imp in all_imports:
                    f.write(imp)
                f.write('\nrouter = APIRouter()\n')
                f.write('logger = logging.getLogger(__name__)\n\n')
                for block in mod_routes:
                    for line in block["lines"]:
                        f.write(line)
        print(f"  wrote {mod_name}.py")

    # Update routes/__init__.py  
    with open(ROUTES_DIR / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Route registration."""\n')
        f.write('def register_routes(app):\n')
        for mod in sorted(groups.keys()):
            f.write(f'    from server.routes.{mod} import router as {mod}_router\n')
            f.write(f'    app.include_router({mod}_router)\n')

    print("\n✅ V2 redistribution complete.")

if __name__ == "__main__":
    main()
