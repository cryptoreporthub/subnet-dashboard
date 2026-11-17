"""Inventory of server.py for the refactor plan in docs/server-refactor-plan.md.

Usage: python scripts/server_inventory.py . /tmp/server_inventory.json
Prints totals and writes every top-level symbol with its span, routes, callers,
function-level imports, and the tests and production modules that reference it.
"""
import ast, json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1]); SRC = ROOT / "server.py"
src = SRC.read_text(); tree = ast.parse(src)
syms = {}   # name -> dict
order = []
def add(name, kind, node, **kw):
    syms[name] = dict(name=name, kind=kind, start=getattr(node, "lineno", 0), end=getattr(node, "end_lineno", 0), **kw); order.append(name)
stmt_other = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        routes = []
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name) and d.func.value.id == "app":
                arg = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else ""
                routes.append(f"{d.func.attr.upper()} {arg}")
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        add(node.name, "route" if routes else "func", node, routes=routes, is_async=isinstance(node, ast.AsyncFunctionDef))
        syms[node.name]["start"] = start
    elif isinstance(node, ast.ClassDef):
        add(node.name, "class", node)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    add(n.id, "global", node)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        pass
    else:
        stmt_other.append((type(node).__name__, node.lineno, node.end_lineno))

# imports
top_imports = []; lazy_imports = defaultdict(list)
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mod = node.module if isinstance(node, ast.ImportFrom) else ",".join(a.name for a in node.names)
        top_imports.append((node.lineno, mod, [a.asname or a.name for a in node.names]))
imported_names = {n for _, _, names in top_imports for n in names}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for n in ast.walk(node):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mod = n.module if isinstance(n, ast.ImportFrom) else ",".join(a.name for a in n.names)
                lazy_imports[node.name].append(mod)

# intra-module deps and global writes
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        refs = set(); writes = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in syms and n.id != node.name:
                refs.add(n.id)
            if isinstance(n, ast.Global):
                writes.update(n.names)
        syms[node.name]["refs"] = sorted(refs); syms[node.name]["global_writes"] = sorted(writes)
        syms[node.name]["lazy_imports"] = sorted(set(lazy_imports.get(node.name, [])))
        syms[node.name]["broad_excepts"] = sum(1 for n in ast.walk(node) if isinstance(n, ast.ExceptHandler) and (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in ("Exception", "BaseException"))))

# external references: files that import server, and attribute names they touch
ext = defaultdict(lambda: defaultdict(int)); importers = defaultdict(int)
files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"], capture_output=True, text=True).stdout.split()
pat_attr = re.compile(r"\b(?:server|srv|_server|server_mod|server_module)\.([A-Za-z_][A-Za-z0-9_]*)")
pat_str = re.compile(r"""["']server\.([A-Za-z_][A-Za-z0-9_]*)""")
pat_from = re.compile(r"from server import ([^\n]+(?:\n[^\n)]*)*?)(?:\n|$)")
pat_setattr = re.compile(r"""setattr\(\s*(?:server|srv|_server|server_mod|server_module)\s*,\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
for f in files:
    if f == "server.py": continue
    t = (ROOT / f).read_text(errors="replace")
    if not re.search(r"^\s*(import server\b|from server import|import server as)", t, re.M) and "server." not in t: continue
    if not re.search(r"(import server\b|from server import|import_module\(\s*[\"']server[\"']|[\"']server\.[A-Za-z_])", t): continue
    importers[f] += 1
    names = set(pat_attr.findall(t)) | set(pat_str.findall(t)) | set(pat_setattr.findall(t))
    for m in re.finditer(r"from server import \(?([^)\n]+(?:\n[^)\n]+)*)\)?", t):
        for nm in re.split(r"[,\s]+", m.group(1)):
            nm = nm.split(" as ")[0].strip("() ")
            if nm.isidentifier(): names.add(nm)
    for nm in names:
        if nm in syms or nm in imported_names:
            ext[nm]["tests" if f.startswith("tests/") else "prod"] += 1
            ext[nm].setdefault("files", 0)
for name in syms:
    syms[name]["ext_tests"] = ext[name].get("tests", 0); syms[name]["ext_prod"] = ext[name].get("prod", 0)
reexported = {n: dict(ext[n]) for n in ext if n in imported_names and n not in syms}

out = dict(order=order, syms=syms, top_imports=top_imports, other_stmts=stmt_other,
           importers=sorted(importers), reexported=reexported, loc=len(src.splitlines()))
json.dump(out, open(sys.argv[2], "w"), indent=1)
funcs = [s for s in syms.values() if s["kind"] in ("func", "route")]
print("loc", out["loc"], "bytes", len(src.encode()))
print("functions", len(funcs), "routes", sum(len(s["routes"]) for s in funcs), "globals", sum(1 for s in syms.values() if s["kind"]=="global"), "classes", sum(1 for s in syms.values() if s["kind"]=="class"))
print("top imports", len(top_imports), "lazy import statements", sum(len(v) for v in lazy_imports.values()), "distinct lazy modules", len({m for v in lazy_imports.values() for m in v}))
print("broad excepts in funcs", sum(s.get("broad_excepts",0) for s in funcs))
print("importer files: tests", sum(1 for f in importers if f.startswith("tests/")), "prod", [f for f in importers if not f.startswith("tests/")])
print("symbols referenced externally:", sum(1 for s in syms.values() if s["ext_tests"] or s["ext_prod"]), "of", len(syms))
print("non-def top-level stmts:", stmt_other)
