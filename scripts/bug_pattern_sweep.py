"""Repo-wide sweep for the bug patterns found in server.py (docs/bug-sweep.md).

Usage: python scripts/bug_pattern_sweep.py [--json out.json]
Read-only. Parses every tracked non-test Python file and prints each hit as file:line.
"""
import ast, json, subprocess, sys
from collections import defaultdict

files = [f for f in subprocess.run(["git", "ls-files", "*.py"], capture_output=True, text=True).stdout.split()
         if not f.startswith(("tests/", "scripts/server_", "scripts/bug_pattern"))]
hits = defaultdict(list)
BLOCKING = {("time", "sleep"), ("requests", "get"), ("requests", "post"), ("requests", "request"), ("subprocess", "run")}

def call_name(n):
    f = n.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name): return (f.value.id, f.attr)
    if isinstance(f, ast.Attribute): return ("", f.attr)
    if isinstance(f, ast.Name): return ("", f.id)
    return ("", "")

def is_route(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "delete", "patch"):
            return d.func.attr
    return None

for path in files:
    try: src = open(path).read(); tree = ast.parse(src)
    except Exception: continue
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        # P1: `with ThreadPoolExecutor` plus result(timeout=): the with-block joins the worker on timeout
        for w in ast.walk(fn):
            if isinstance(w, ast.With) and any(isinstance(i.context_expr, ast.Call) and call_name(i.context_expr)[1] == "ThreadPoolExecutor" for i in w.items):
                if any(isinstance(c, ast.Call) and call_name(c)[1] in ("result", "wait", "as_completed") and any(k.arg == "timeout" for k in c.keywords) for c in ast.walk(w)):
                    hits["timeout_joined_by_with_block"].append(f"{path}:{w.lineno}")
        # P2: blocking call directly inside async def (not in a nested sync def)
        if isinstance(fn, ast.AsyncFunctionDef):
            stack = list(fn.body)
            while stack:
                n = stack.pop()
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)): continue
                if isinstance(n, ast.Call) and call_name(n) in BLOCKING: hits["blocking_call_in_async"].append(f"{path}:{n.lineno} {'.'.join(call_name(n))}")
                if isinstance(n, ast.Call) and call_name(n) == ("", "open"): hits["file_io_in_async"].append(f"{path}:{n.lineno}")
                stack.extend(ast.iter_child_nodes(n))
        # P3: mutable default argument
        for d in fn.args.defaults + fn.args.kw_defaults:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)): hits["mutable_default_arg"].append(f"{path}:{fn.lineno} {fn.name}")
        # P4: route handler returns the exception text
        method = is_route(fn)
        if method:
            for h in ast.walk(fn):
                if isinstance(h, ast.ExceptHandler) and h.name:
                    for c in ast.walk(h):
                        if isinstance(c, ast.Return) and any(isinstance(x, ast.Call) and call_name(x) == ("", "str") and x.args and isinstance(x.args[0], ast.Name) and x.args[0].id == h.name for x in ast.walk(c)):
                            hits["route_returns_exception_text"].append(f"{path}:{c.lineno} {fn.name}"); break
            # P5: GET handler that calls a writer by name
            if method == "get":
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call) and call_name(c)[1].startswith(("record_", "save_", "write_", "append_", "persist", "safe_write")):
                        hits["get_route_calls_writer"].append(f"{path}:{c.lineno} {fn.name} -> {call_name(c)[1]}")
    for n in ast.walk(tree):
        # P6: isoformat() + "Z" on an aware datetime gives +00:00Z
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and isinstance(n.right, ast.Constant) and n.right.value == "Z" \
           and isinstance(n.left, ast.Call) and call_name(n.left)[1] == "isoformat":
            inner = ast.dump(n.left)
            hits["isoformat_plus_Z_aware" if "timezone" in inner or "utc" in inner.lower() and "utcnow" not in inner else "isoformat_plus_Z_check"].append(f"{path}:{n.lineno}")
        # P7: except Exception: pass
        if isinstance(n, ast.ExceptHandler) and (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in ("Exception", "BaseException"))) \
           and len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
            hits["silent_except_pass"].append(f"{path}:{n.lineno}")
        # P8: json.dump to an open file handle (not atomic)
        if isinstance(n, ast.Call) and call_name(n) == ("json", "dump"):
            hits["non_atomic_json_dump"].append(f"{path}:{n.lineno}")
        # P9: naive utcnow
        if isinstance(n, ast.Call) and call_name(n)[1] == "utcnow":
            hits["naive_utcnow"].append(f"{path}:{n.lineno}")
        # P10: hardcoded relative data path
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(("data/", "config/")) and n.value.endswith((".json", ".db", ".jsonl")):
            hits["hardcoded_relative_data_path"].append(f"{path}:{n.lineno} {n.value}")

for k in sorted(hits, key=lambda k: len(hits[k])): print(f"{k}: {len(hits[k])}")
if "--json" in sys.argv: json.dump(hits, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
