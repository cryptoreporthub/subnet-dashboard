#!/usr/bin/env python3
"""Flag the two failure shapes behind PR #1578's worst bugs, with a ratchet.

Rules (AST, stdlib only):

  read-as-empty   A handler catches a read failure other than FileNotFoundError
                  alone and returns an empty container. A torn or corrupt file
                  then looks like "no history", and the next write overwrites it.
  swallow-to-empty A broad handler (Exception, BaseException, bare except) assigns
                  an empty container. A failed read becomes "nothing exists".

A hit is not a verdict. A cache that treats a corrupt file as empty is fine. The
ratchet records today's hits in scripts/invariants_baseline.json by rule, file,
and function name, so only NEW hits fail. Line numbers are not part of the key.

Usage:
  python scripts/check_invariants.py --list                 print every hit
  python scripts/check_invariants.py --check                fail on hits not in baseline
  python scripts/check_invariants.py --list --root DIR
                              scan another tree (proof runs)
  python scripts/check_invariants.py --write-baseline
                              accept current hits (human review first)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Set

SCAN_DIRS = ("internal", "message_intel")
SCAN_FILES = ("server.py",)
BASELINE = Path("scripts/invariants_baseline.json")
BROAD = {"Exception", "BaseException"}
EMPTY_CALLS = {"list", "dict", "set"}
# A swallowed read matters when the same function then writes. Names are a
# heuristic for "this function persists state", so a pure dashboard
# builder is not flagged.
WRITE_VERBS = (
    "record",
    "save",
    "write",
    "append",
    "commit",
    "persist",
    "dump",
    "replace",
    "mutate",
    "nudge",
    "apply",
)


def _handler_types(handler: ast.ExceptHandler) -> Set[str]:
    if handler.type is None:
        return {"BaseException"}
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names: Set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _is_empty_container(node: Optional[ast.AST]) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return not getattr(node, "elts", None) and not getattr(node, "keys", None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in EMPTY_CALLS and not node.args and not node.keywords
    return False


def _body_returns_empty(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(s, ast.Return) and _is_empty_container(s.value) for s in handler.body
    )


def _body_assigns_empty(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(s, ast.Assign) and _is_empty_container(s.value) for s in handler.body
    )


def _try_reads(node: ast.Try) -> bool:
    for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in {"open", "load", "loads", "read_text", "read", "read_bytes"}:
                return True
    return False


def _hits_in_module(tree: ast.AST, rel: str) -> Iterator[dict]:
    """Yield hits, attributing each try to its nearest enclosing function.

    Nested defs are not double counted.
    """
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    seen: dict = {}
    tries = sorted(
        (n for n in ast.walk(tree) if isinstance(n, ast.Try)), key=lambda n: n.lineno
    )
    for node in tries:
        fn = next(
            (
                p
                for p in _ancestors(node, parents)
                if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            tree,
        )
        for handler in node.handlers:
            types = _handler_types(handler)
            broad = bool(types & BROAD)
            if (
                _body_returns_empty(handler)
                and _try_reads(node)
                and types - {"FileNotFoundError"}
            ):
                yield _hit("read-as-empty", rel, fn, handler, sorted(types), seen)
            if broad and _body_assigns_empty(handler) and _writes(fn):
                yield _hit("swallow-to-empty", rel, fn, handler, sorted(types), seen)


def _writes(fn: ast.AST) -> bool:
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if any(v in name.lower() for v in WRITE_VERBS):
                return True
    return False


def _ancestors(node: ast.AST, parents: dict) -> Iterator[ast.AST]:
    while node in parents:
        node = parents[node]
        yield node


def _hit(
    rule: str,
    rel: str,
    fn: ast.AST,
    handler: ast.ExceptHandler,
    types: List[str],
    seen: dict,
) -> dict:
    """Key is readable and interpreter-independent.

    Parts: rule, file, function, caught types, and the occurrence index in source
    order. A hash of ast.dump would change across Python versions.
    """
    fn_name = getattr(fn, "name", "<module>")
    slot = (rule, rel, fn_name, ",".join(types))
    seen[slot] = seen.get(slot, 0) + 1
    return {
        "rule": rule,
        "file": rel,
        "function": fn_name,
        "line": handler.lineno,
        "caught": types,
        "key": f"{rule}|{rel}|{fn_name}|{','.join(types)}|#{seen[slot]}",
    }


def scan(root: Path) -> List[dict]:
    files: List[Path] = []
    for d in SCAN_DIRS:
        files.extend(sorted((root / d).rglob("*.py")))
    files.extend(root / f for f in SCAN_FILES)
    hits: List[dict] = []
    for path in files:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            hits.append(
                {
                    "rule": "parse-error",
                    "file": rel,
                    "function": "",
                    "line": exc.lineno or 0,
                    "caught": [],
                    "key": f"parse-error|{rel}",
                }
            )
            continue
        hits.extend(_hits_in_module(tree, rel))
    return hits


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--root", default=".", help="tree to scan (default: cwd)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    hits = scan(root)

    if args.list:
        for h in hits:
            print(
                f"{h['rule']}\t{h['file']}:{h['line']}\t{h['function']}"
                f"\tcaught={','.join(h['caught'])}"
            )
        print(f"hits: {len(hits)}")
        return 0

    baseline_path = root / BASELINE
    if args.write_baseline:
        payload = sorted(
            ({k: h[k] for k in ("rule", "file", "function", "key")} for h in hits),
            key=lambda h: (h["rule"], h["file"], h["function"], h["key"]),
        )
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(payload)} accepted hits to {BASELINE}")
        return 0

    accepted = (
        {e["key"] for e in json.loads(baseline_path.read_text(encoding="utf-8"))}
        if baseline_path.exists()
        else set()
    )
    new = [h for h in hits if h["key"] not in accepted]
    for h in new:
        print(
            f"NEW {h['rule']}\t{h['file']}:{h['line']}\t{h['function']}"
            f"\tcaught={','.join(h['caught'])}"
        )
    print(f"check: {len(hits)} hits, {len(hits) - len(new)} accepted, {len(new)} new")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
