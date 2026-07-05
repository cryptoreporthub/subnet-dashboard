#!/usr/bin/env python3
"""Modular splitter — reads server.py, writes server/ package."""
import re, os, shutil, ast
from pathlib import Path

ROOT = Path(".")
SRC = ROOT / "server.py"

with open(SRC, encoding="utf-8") as f:
    lines = f.readlines()

print(f"Read {len(lines)} lines from server.py")

# Find the LAST @app.<method> route function body end
n = len(lines)
last_route_end = 0
i = 0
while i < n:
    s = lines[i].strip()
    if not re.match(r'^@app.(get|post|put|delete|patch|api_route)(', s):
        i += 1
        continue
    # Skip consecutive decorators
    while i < n:
        s2 = lines[i].strip()
        if s2.startswith('@'):
            i += 1
        elif re.match(r'^(async )?def ', s2):
            break
        elif s2 == '' or s2.startswith('#'):
            i += 1
        else:
            break
    if i >= n:
        break
    s2 = lines[i].strip()
    if not re.match(r'^(async )?def ', s2):
        continue
    base_indent = len(lines[i]) - len(lines[i].lstrip())
    i += 1
    while i < n:
        body = lines[i].strip()
        if body:
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            if current_indent <= base_indent:
                break
        i += 1
    last_route_end = max(last_route_end, i)

print(f"Last route body ends at line {last_route_end}")

preamble = lines[:last_route_end]
route_start = 0
for idx, ln in enumerate(preamble):
    if re.match(r'^@app.(get|post|put|delete|patch|api_route)(', ln.strip()):
        route_start = idx
        break

config_lines = preamble[:route_start]
route_lines = preamble[route_start:]
tail_lines = lines[last_route_end:]

print(f"config.py: {len(config_lines)} lines")
print(f"routes.py: {len(route_lines)} lines")
print(f"__init__.py: {len(tail_lines)} lines")

# Clean and create
pkg = ROOT / "server"
shutil.rmtree(pkg, ignore_errors=True)
pkg.mkdir(parents=True, exist_ok=True)

# --- server/config.py ---
with open(pkg / "config.py", "w", encoding="utf-8") as f:
    f.write('"""Server configuration."""\n')
    f.writelines(config_lines)
print(f"Wrote server/config.py ({len(config_lines)} lines)")

# --- server/routes.py ---
with open(pkg / "routes.py", "w", encoding="utf-8") as f:
    f.write('"""All API and web routes."""\n')
    f.write("from fastapi import APIRouter, Request\n")
    f.write("from fastapi.responses import JSONResponse, PlainTextResponse\n")
    f.write("from server.config import *  # noqa: F403\n")
    f.write("\n")
    f.write("logger = logging.getLogger(__name__)\n")
    f.write("router = APIRouter()\n")
    f.write("\n")
    for line in route_lines:
        fixed = line
        for method in ["get", "post", "put", "delete", "patch", "api_route"]:
            fixed = fixed.replace(f"@app.{method}(", f"@router.{method}(")
        f.write(fixed)
print(f"Wrote server/routes.py ({len(route_lines)} lines)")

# --- server/__init__.py ---
with open(pkg / "__init__.py", "w", encoding="utf-8") as f:
    f.write('"""Subnet Dashboard server package."""\n')
    f.write("from server.config import *  # noqa: F403\n")
    f.write("\n")
    f.writelines(tail_lines)
print(f"Wrote server/__init__.py ({len(tail_lines)} lines)")

# --- server.py shim ---
with open(ROOT / "server.py", "w", encoding="utf-8") as f:
    f.write('"""Subnet Dashboard — modular entry point."""\n')
    f.write("import os\n")
    f.write("from server import app\n")
    f.write("\n")
    f.write('if __name__ == "__main__":\n')
    f.write("    import uvicorn\n")
    f.write('    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))\n')
print("Wrote server.py shim")

# --- Cleanup ---
for old in ["judge_app.py", "council_app.py",
            "scripts/split_server.py", "scripts/recover_tail.py",
            ".github/workflows/split-server.yml", ".github/workflows/restore-server.yml"]:
    p = ROOT / old
    if p.exists():
        p.unlink()
        print(f"Removed {old}")

df = ROOT / "Dockerfile"
if df.exists():
    content = df.read_text()
    content = content.replace("council_app:app", "server:app")
    df.write_text(content)
    print("Fixed Dockerfile")

pf = ROOT / "Procfile"
if pf.exists():
    content = pf.read_text()
    content = content.replace("council_app:app", "server:app")
    content = content.replace("judge_app:app", "server:app")
    pf.write_text(content)
    print("Fixed Procfile")

# --- Verify ---
for path in ["server.py", "server/config.py", "server/routes.py", "server/__init__.py"]:
    try:
        with open(ROOT / path) as fh:
            ast.parse(fh.read())
        print(f"  {path}: OK")
    except SyntaxError as e:
        print(f"  {path}: SYNTAX ERROR — {e}")
        with open(ROOT / path) as fh:
            content = fh.read()
        lines = content.split('\n')
        if hasattr(e, 'lineno') and e.lineno:
            for j in range(max(0, e.lineno - 2), min(len(lines), e.lineno + 2)):
                print(f"    {j+1}: {lines[j][:120]}")

print("\nDone!")
