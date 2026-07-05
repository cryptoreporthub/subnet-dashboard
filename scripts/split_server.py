#!/usr/bin/env python3
"""Split server.py monolith into server/ package."""
import re, os, shutil, ast
from pathlib import Path

ROOT = Path(".")
SRC = ROOT / "server.py"

with open(SRC, encoding="utf-8") as f:
    lines = f.readlines()

print(f"Read {len(lines)} lines")

# Find all @app. decorator line numbers
decs = [i + 1 for i, ln in enumerate(lines) if re.match(r"^@app\.", ln.strip())]

if not decs:
    print("ERROR: No @app. decorators found!")
    import sys; sys.exit(1)

FIRST_ROUTE = decs[0]
LAST_DEC = decs[-1]
print(f"First route at line {FIRST_ROUTE}, last decorator at line {LAST_DEC}")

# Find the end of the last route function body by scanning forward from LAST_DEC
idx = LAST_DEC - 1
n = len(lines)
while idx < n:
    s = lines[idx].strip()
    if s.startswith("@app.") or s == "" or s.startswith("#"):
        idx += 1
        continue
    if s.startswith("def ") or s.startswith("async def "):
        break
    idx += 1

# We are now on the def line of the last route
base_indent = len(lines[idx]) - len(lines[idx].lstrip())
print(f"  def at line {idx+1}, indent={base_indent}")
idx += 1
while idx < n:
    s = lines[idx].strip()
    if s:
        current_indent = len(lines[idx]) - len(lines[idx].lstrip())
        if current_indent <= base_indent:
            break
    idx += 1

LAST_END = idx + 1
print(f"LAST_END={LAST_END}")

# Split
config_lines = lines[:FIRST_ROUTE - 1]
route_lines = lines[FIRST_ROUTE - 1 : LAST_END - 1]
tail_lines = lines[LAST_END - 1:]

print(f"  config: {len(config_lines)} lines")
print(f"  routes: {len(route_lines)} lines")
print(f"  tail:   {len(tail_lines)} lines")

# Write files
pkg = ROOT / "server"
shutil.rmtree(pkg, ignore_errors=True)
pkg.mkdir(parents=True, exist_ok=True)

with open(pkg / "config.py", "w", encoding="utf-8") as f:
    f.write("\"\"\"Server configuration.\"\"\"\n")
    f.writelines(config_lines)
print(f"Wrote server/config.py ({len(config_lines)} lines)")

with open(pkg / "routes.py", "w", encoding="utf-8") as f:
    f.write("\"\"\"All API and web routes.\"\"\"\n")
    f.write("from fastapi import APIRouter, Request\n")
    f.write("from fastapi.responses import JSONResponse, PlainTextResponse\n")
    f.write("from server.config import *  # noqa: F403\n")
    f.write("\n")
    f.write("logger = logging.getLogger(__name__)\n")
    f.write("router = APIRouter()\n\n")
    for ln in route_lines:
        fixed = ln
        for m in ["get", "post", "put", "delete", "patch", "api_route"]:
            fixed = fixed.replace(f"@app.{m}(", f"@router.{m}(")
        f.write(fixed)
print(f"Wrote server/routes.py ({len(route_lines)} lines)")

with open(pkg / "__init__.py", "w", encoding="utf-8") as f:
    f.write("\"\"\"Subnet Dashboard server package.\"\"\"\n")
    f.write("from server.config import *  # noqa: F403\n\n")
    f.writelines(tail_lines)
print(f"Wrote server/__init__.py ({len(tail_lines)} lines)")

with open(ROOT / "server.py", "w", encoding="utf-8") as f:
    f.write("\"\"\"Subnet Dashboard — modular entry point.\"\"\"\n")
    f.write("import os\n")
    f.write("from server import app\n\n")
    f.write("if __name__ == \"__main__\":\n")
    f.write("    import uvicorn\n")
    f.write("    uvicorn.run(app, host=\"0.0.0.0\", port=int(os.environ.get(\"PORT\", 5000)))\n")
print("Wrote server.py shim")

# Cleanup
for old in ["judge_app.py", "council_app.py",
            "scripts/split_server.py", "scripts/recover_tail.py",
            "scripts/modular_split.py", "scripts/test.py"]:
    p = ROOT / old
    if p.exists():
        p.unlink()
        print(f"Removed {old}")

df = ROOT / "Dockerfile"
if df.exists():
    df.write_text(df.read_text().replace("council_app:app", "server:app"))
    print("Fixed Dockerfile")

pf = ROOT / "Procfile"
if pf.exists():
    content = pf.read_text()
    content = content.replace("council_app:app", "server:app")
    content = content.replace("judge_app:app", "server:app")
    pf.write_text(content)
    print("Fixed Procfile")

# Verify
for path in ["server.py", "server/config.py", "server/routes.py", "server/__init__.py"]:
    try:
        with open(ROOT / path) as fh:
            ast.parse(fh.read())
        print(f"  {path}: OK")
    except SyntaxError as e:
        print(f"  {path}: SYNTAX ERROR — {e}")

print("\nDone!")