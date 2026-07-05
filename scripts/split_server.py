Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/scripts/split_server.py

Markdown Content:
#!/usr/bin/env python3
"""Proper splitter — reads full server.py from git, preserves ALL tail code."""
import subprocess, re, sys, os, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIG = "d44d1439bb9cc9b9005bc9ecbd588f10edc81bd7"

def get_original():
    """Get the full original server.py from git history (pre-split)."""
    r = subprocess.run(["git", "show", f"{ORIG}:server.py"],
        capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"git show failed: {r.stderr}")
    return r.stdout.split("\n")

def find_last_route_end(lines):
    """Find the line index right after the last @app.route function body."""
    last_end = 0
    i = 0
    n = len(lines)
    while i < n:
        if not re.match(r"^\s*@app\.(get|post|put|delete|patch|api_route)\(", lines[i]):
            i += 1
            continue
        # Found a decorator — find the following def
        while i < n:
            s = lines[i].strip()
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
        s = lines[i].strip()
        if not re.match(r"^(async\s+)?def\s+", s):
            continue
        # Found the function def — consume body
        base_indent = len(lines[i]) - len(s)
        i += 1
        while i < n:
            body_s = lines[i].strip()
            if body_s:
                indent = len(lines[i]) - len(body_s)
                if indent <= base_indent:
                    break
            i += 1
        last_end = i
    return last_end

def extract_imports(lines):
    imps = []
    for l in lines:
        s = l.strip()
        if re.match(r"^(import |from )", s):
            imps.append(l)
    return list(dict.fromkeys(imps))

def extract_route_blocks(lines):
    """Parse route functions into blocks keyed by URL prefix."""
    n = len(lines)
    route_map = [
        (r"^/health$|^/api/health$|^/api/freshness$|^/favicon", "system"),
        (r"^/api/subnets", "subnets"),
        (r"^/api/judges|^/api/council|^/api/paper-portfolio|^/api/postmortems|^/api/portfolios|^/api/oracle", "judges"),
        (r"^/api/simivision|^/api/top-pick", "simivision"),
        (r"^/api/indicators", "indicators"),
        (r"^/api/mindmap", "mindmap"),
        (r"^/api/learning|^/api/scenario-memory", "learning"),
        (r"^/api/pump-analytics", "pumps"),
        (r"^/api/rotation-tokens", "tokens"),
    ]
    groups = {}
    i = 0
    while i < n:
        if not re.match(r"^\s*@app\.(get|post|put|delete|patch|api_route)\(", lines[i]):
            i += 1
            continue
        block_start = i
        # Collect decorators
        while i < n:
            s = lines[i].strip()
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
        s = lines[i].strip()
        if not re.match(r"^(async\s+)?def\s+", s):
            continue
        base_indent = len(lines[i]) - len(s)
        i += 1
        while i < n:
            body_s = lines[i].strip()
            if body_s:
                indent = len(lines[i]) - len(body_s)
                if indent <= base_indent:
                    break
            i += 1
        block_end = i
        block_lines = lines[block_start:block_end]
        # Determine module
        first_deco = lines[block_start]
        url_match = re.search(r"""['"](/[^'"]*)""", first_deco)
        url_path = url_match.group(1) if url_match else "/"
        module = "web"
        for pat, mod in route_map:
            if re.match(pat, url_path):
                module = mod
                break
        groups.setdefault(module, []).append((url_path, block_lines))
    return groups

def find_all_globals_and_helpers(tail_lines):
    """Find ALL top-level functions and global variable assignments in tail."""
    defs = []
    for line in tail_lines:
        stripped = line.strip()
        if stripped.startswith('@') and re.match(r"^(async\s+)?def\s+", ""):
            continue  # Decorators handled with defs
        m = re.match(r"^(async\s+)?def\s+(\w+)\(", stripped)
        if m:
            defs.append(m.group(2))
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", stripped)
        if m:
            defs.append(m.group(1))
        m = re.match(r"^(_\w+)\s*=", stripped)
        if m:
            defs.append(m.group(1))
    return list(dict.fromkeys(defs))

def main():
    print("=== Reading original server.py from git ===")
    orig = get_original()
    print(f"  {len(orig)} lines total")

    # Find route/tail boundary
    tail_start = find_last_route_end(orig)
    header_lines = orig[:tail_start]
    tail_lines = orig[tail_start:]
    print(f"  Header (incl routes): {len(header_lines)} lines")
    print(f"  Tail: {len(tail_lines)} lines")

    # Extract imports from header
    all_imports = extract_imports(header_lines)
    print(f"  Unique imports: {len(all_imports)}")

    # Extract route blocks
    groups = extract_route_blocks(header_lines)
    total_routes = sum(len(v) for v in groups.values())
    print(f"  Routes: {total_routes} across {len(groups)} modules")
    for mod, blocks in sorted(groups.items()):
        print(f"    {mod}: {len(blocks)}")

    # Find all globals/helpers defined in tail
    tail_defs = find_all_globals_and_helpers(tail_lines)
    print(f"  Tail defines: {len(tail_defs)} symbols")
    for d in tail_defs[:40]:
        print(f"    {d}")

    # --- WRITE FILES ---
    print("\n=== Writing modular structure ===")

    pkg = ROOT / "server"
    routes_dir = pkg / "routes"
    services_dir = pkg / "services"

    # Clean old dirs
    shutil.rmtree(pkg, ignore_errors=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    services_dir.mkdir(parents=True, exist_ok=True)

    # server/config.py — keep existing header + append ALL tail code
    # But the existing config.py may be stale. Better: extract from original.
    # Find where routes start
    route_start = None
    for i, line in enumerate(header_lines):
        if re.match(r"^\s*@app\.(get|post|put|delete|patch|api_route)\(", line):
            route_start = i
            break
    if route_start is None:
        route_start = len(header_lines)
    
    config_body = header_lines[:route_start]  # Everything before first route
    config_body.extend(tail_lines)  # Append all tail code
    
    # Strip any remaining @app.route references from config
    config_body = [l for l in config_body if not re.match(r"^\s*@app\.(get|post|delete|put|patch)", l)]
    
    with open(pkg / "config.py", "w", encoding="utf-8") as f:
        f.write('"""Server configuration — constants, globals, helpers, and scheduler setup."""\n')
        for line in config_body:
            f.write(line)
    print(f"  server/config.py: {len(config_body)} lines")

    # server/state.py
    with open(pkg / "state.py", "w", encoding="utf-8") as f:
        f.write('"""Global state placeholder."""\n')
    print("  server/state.py: placeholder")

    # server/__init__.py — app factory
    # Find create_app and lifespan in tail
    create_app_start = None
    main_start = None
    lifespan_start = None
    for i, line in enumerate(tail_lines):
        s = line.strip()
        if s.startswith("def create_app"):
            create_app_start = i
        if s.startswith("if __name__"):
            main_start = i
        if "lifespan" in s and s.startswith("@"):
            lifespan_start = i

    # Write __init__.py with full tail
    init_body = []
    init_body.append('"""Subnet Dashboard server package."""\n')
    for imp in all_imports:
        init_body.append(imp)
    init_body.append('\n')
    init_body.append('from server.config import *  # noqa: F403\n')
    init_body.append('\n')
    
    # Include tail content minus the if __name__ block
    for i, line in enumerate(tail_lines):
        if main_start is not None and i >= main_start:
            continue
        init_body.append(line)
    
    init_body.append('\n')
    if main_start is not None:
        for line in tail_lines[main_start:]:
            init_body.append(line)
    
    with open(pkg / "__init__.py", "w", encoding="utf-8") as f:
        f.write("".join(init_body))
    print(f"  server/__init__.py: {len(init_body)} lines")

    # server/routes/__init__.py
    with open(routes_dir / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Route registration."""\n')
        f.write('def register_routes(app):\n')
        for mod in sorted(groups.keys()):
            f.write(f'    from server.routes.{mod} import router as {mod}_router\n')
            f.write(f'    app.include_router({mod}_router)\n')
    print(f"  server/routes/__init__.py: {len(groups)} modules registered")

    # server/services/__init__.py
    with open(services_dir / "__init__.py", "w", encoding="utf-8") as f:
        f.write('"""Background services."""\n')

    # Write each route module
    for mod_name, blocks in groups.items():
        with open(routes_dir / f"{mod_name}.py", "w", encoding="utf-8") as f:
            f.write(f'"""Routes: {mod_name}."""\n')
            f.write('from fastapi import APIRouter, Request\n')
            f.write('from fastapi.responses import JSONResponse, PlainTextResponse\n')
            f.write('import logging, json, os\n')
            f.write('from datetime import datetime\n')
            f.write('from typing import Optional, Dict, List, Any\n')
            f.write('from server.config import *  # noqa: F403\n')
            f.write('\n')
            f.write('logger = logging.getLogger(__name__)\n')
            f.write('router = APIRouter()\n\n')
            for url_path, block in blocks:
                for line in block:
                    fixed = line
                    for m in ['get', 'post', 'put', 'delete', 'patch', 'api_route']:
                        fixed = fixed.replace(f'@app.{m}(', f'@router.{m}(')
                    f.write(fixed)
                f.write('\n')
        print(f"  server/routes/{mod_name}.py: {len(blocks)} routes")

    # server.py shim
    shim_parts = []
    shim_parts.append('"""Subnet Dashboard — modular entry point."""\n')
    
    # Check if tail has create_app or app = FastAPI
    has_create_app = any("def create_app" in l for l in tail_lines)
    has_app_assignment = any(re.match(r"^app\s*=\s*FastAPI", l.strip()) for l in tail_lines)
    
    if has_create_app:
        shim_parts.append('import os\n')
        shim_parts.append('from server import create_app\n')
        shim_parts.append('app = create_app()\n\n')
    elif has_app_assignment:
        shim_parts.append('from server import *  # noqa: F403\n')
    else:
        shim_parts.append('from server import app  # noqa: F401\n')
    
    shim_parts.append('if __name__ == "__main__":\n')
    shim_parts.append('    import uvicorn\n')
    shim_parts.append('    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))\n')
    
    with open(ROOT / "server.py", "w", encoding="utf-8") as f:
        f.write("".join(shim_parts))
    print("  server.py: shim updated")

    # Remove old wrappers
    for old in ["judge_app.py", "council_app.py"]:
        p = ROOT / old
        if p.exists():
            p.unlink()
            print(f"  Removed {old}")

    # Fix Procfile
    pf = ROOT / "Procfile"
    content = pf.read_text() if pf.exists() else ""
    for old_ref in ["council_app:app", "judge_app:app"]:
        content = content.replace(old_ref, "server:app")
    pf.write_text(content)
    print("  Procfile: updated")

    print("\n==

[read_links truncated 697 chars from this runtime tool output. The full content is stored with the tool result.]
# v3 retrigger
