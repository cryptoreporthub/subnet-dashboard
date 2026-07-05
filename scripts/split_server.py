Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/scripts/split_server.py

Markdown Content:
#!/usr/bin/env python3
"""Simple robust splitter — three-file split, nothing lost."""
import subprocess, re, sys, os, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIG = "d44d1439bb9cc9b9005bc9ecbd588f10edc81bd7"

def get_original():
    r = subprocess.run(["git", "show", f"{ORIG}:server.py"],
        capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"git show failed: {r.stderr}")
    return r.stdout.split("\n")

def main():
    print("=== Reading original server.py ===")
    orig = get_original()
    n = len(orig)
    print(f"  {n} lines")

    # Find: first @app decorator and last @app decorator function end
    first_route = None
    last_route_end = 0
    i = 0
    while i < n:
        if re.match(r"^\s*@app\.(get|post|put|delete|patch|api_route)\(", orig[i]):
            if first_route is None:
                first_route = i
            # Find def line
            while i < n:
                s = orig[i].strip()
                if s.startswith('@'):
                    i += 1
                elif re.match(r"^(async\s+)?def\s+", s):
                    break
                elif s == '' or s.startswith('#'):
                    i += 1
                else:
                    break
            if i >= n:
                break
            s = orig[i].strip()
            if not re.match(r"^(async\s+)?def\s+", s):
                continue
            base_indent = len(orig[i]) - len(s)
            i += 1
            while i < n:
                body = orig[i].strip()
                if body and len(orig[i]) - len(body) <= base_indent:
                    break
                i += 1
            last_route_end = i
        else:
            i += 1

    print(f"  First route: line {first_route}")
    print(f"  Last route end: line {last_route_end}")

    # Three-way split
    preamble = orig[:first_route] if first_route else orig
    route_lines = orig[first_route:last_route_end] if first_route else []
    tail_lines = orig[last_route_end:]

    print(f"  Preamble (imports/constants/helpers): {len(preamble)} lines")
    print(f"  Route functions: {len(route_lines)} lines")
    print(f"  Tail (app factory, lifespan, __main__): {len(tail_lines)} lines")

    # Clean and create dirs
    pkg = ROOT / "server"
    routes_dir = pkg / "routes"
    services_dir = pkg / "services"
    shutil.rmtree(pkg, ignore_errors=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    services_dir.mkdir(parents=True, exist_ok=True)

    # --- server/config.py: all preamble (imports, constants, stub helpers) ---
    with open(pkg / "config.py", "w", encoding="utf-8") as f:
        f.write('"""Server configuration — imports, constants, and safe fallbacks."""\n')
        for line in preamble:
            f.write(line + "\n")
    print(f"  server/config.py written ({len(preamble)} lines)")

    # --- server/routes/all.py: all routes in one file, converted from @app to @router ---
    with open(routes_dir / "all.py", "w", encoding="utf-8") as f:
        f.write('"""All API and web routes — originally from server.py."""\n')
        f.write('from fastapi import APIRouter, Request\n')
        f.write('from server.config import *  # noqa: F403\n')
        f.write('\n')
        f.write('logger = logging.getLogger(__name__)\n')
        f.write('router = APIRouter()\n\n')
        for line in route_lines:
            fixed = line
            for method in ['get', 'post', 'put', 'delete', 'patch', 'api_route']:
                fixed = fixed.replace(f'@app.{method}(', f'@router.{method}(')
            f.write(fixed + "\n")
    print(f"  server/routes/all.py written ({len(route_lines)} lines)")

    # --- server/routes/__init__.py ---
    with open(routes_dir / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Route registration."""\n')
        f.write('def register_routes(app):\n')
        f.write('    from server.routes.all import router\n')
        f.write('    app.include_router(router)\n')
    print("  server/routes/__init__.py written")

    # --- server/services/__init__.py ---
    with open(services_dir / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Background services."""\n')

    # --- server/__init__.py: tail code (app factory, lifespan, __main__) ---
    with open(pkg / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Subnet Dashboard server package."""\n')
        f.write('from server.config import *  # noqa: F403\n')
        f.write('\n')
        for line in tail_lines:
            f.write(line + "\n")
        f.write('\n')
    print(f"  server/__init__.py written ({len(tail_lines)} lines")

    # --- server/state.py (placeholder) ---
    with open(pkg / "state.py", "w", encoding="utf-8") as f:
        f.write('"""Global state placeholder."""\n')

    # --- server.py shim ---
    with open(ROOT / "server.py", "w", encoding="utf-8") as f:
        f.write('"""Subnet Dashboard — modular entry point."""\n')
        f.write('import os\n')
        f.write('from server import app\n')
        f.write('\n')
        f.write('if __name__ == "__main__":\n')
        f.write('    import uvicorn\n')
        f.write('    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))\n')
    print("  server.py shim written")

    # Remove old wrappers
    for old in ["judge_app.py", "council_app.py"]:
        p = ROOT / old
        if p.exists():
            p.unlink()
            print(f"  Removed {old}")

    # Fix Procfile
    pf = ROOT / "Procfile"
    content = pf.read_text() if pf.exists() else ""
    for ref in ["council_app:app", "judge_app:app"]:
        if ref in content:
            content = content.replace(ref, "server:app")
            pf.write_text(content)
            print(f"  Procfile: {ref} -> server:app")

    print("\n\u2705 Done. Commit and push to deploy.")

if __name__ == "__main__":
    main()

# v5: preserve line endings
