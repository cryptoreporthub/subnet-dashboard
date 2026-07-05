#!/usr/bin/env python3
"""Recover tail code from original server.py in git history."""
import subprocess, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIG = "d44d1439bb9cc9b9005bc9ecbd588f10edc81bd7"

def get_orig():
    r = subprocess.run(["git", "show", f"{ORIG}:server.py"],
        capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0: sys.exit(f"git show failed: {r.stderr}")
    return r.stdout.split("\n")

def find_last_route(lines):
    "Return index after the last @app.route/def function."
    last_end = 0
    i = 0
    n = len(lines)
    while i < n:
        if not re.match(r"\s*@app\.", lines[i]):
            i += 1; continue
        while i < n and not re.match(r"\s*(async\s+)?def\s+", lines[i]):
            i += 1
        if i >= n: break
        indent = len(lines[i]) - len(lines[i].lstrip())
        i += 1
        while i < n:
            s = lines[i].strip()
            if s and len(lines[i]) - len(s) <= indent:
                break
            i += 1
        last_end = i
    return last_end

def main():
    print("Fetching original server.py...")
    orig = get_orig()
    print(f"  {len(orig)} lines")
    
    tail_start = find_last_route(orig)
    tail = orig[tail_start:]
    print(f"  Tail: {len(tail)} lines starting at line {tail_start}")
    
    # Find create_app or app = FastAPI in tail
    app_setup = []
    main_block = []
    in_main = False
    for line in tail:
        if re.match(r"^if __name__", line.strip()):
            in_main = True
        if in_main:
            main_block.append(line)
        else:
            app_setup.append(line)
    
    # Write tail as backup
    (ROOT / "server" / "_original_tail.py").write_text(
        "\n".join(tail), encoding="utf-8")
    print("  Saved server/_original_tail.py")
    
    # Fix Procfile
    pf = ROOT / "Procfile"
    content = pf.read_text() if pf.exists() else ""
    new = content.replace("council_app:app", "server:app")
    if new != content:
        pf.write_text(new)
        print("  Procfile: council_app:app -> server:app")
    else:
        print("  Procfile already correct")
    
    print("\nDone.")

if __name__ == "__main__":
    main()