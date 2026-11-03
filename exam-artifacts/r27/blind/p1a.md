# Blind package: p1a

## PR title
chore: drop unused census index helper

## PR body
Removes an internal helper and its dedicated tests that no longer ship in production builds.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000001",
  "mc": "missing",
  "cursor": "missing",
  "ditto": "missing",
  "replit": "missing",
  "suite": "clean",
  "replitTagged": false,
  "next": "review"
}
```

## Diff
### `internal/r25_stale_index.py`
```diff
@@ -1,6 +0,0 @@
-"""Unused census index (removed with v3 pipeline)."""
-from __future__ import annotations
-
-
-def index_netuid(netuid: int) -> int:
-    return netuid
```

## Diff
### `tests/test_r25_stale_index.py`
```diff
@@ -1,9 +0,0 @@
-from internal.r25_stale_index import index_netuid
-
-
-def test_index_non_negative():
-    assert index_netuid(3) == 3
-
-
-def test_index_zero():
-    assert index_netuid(0) == 0
```

## Repo files (head, read-only context)

### `internal/r25_stale_index.py`
_(absent at head)_

### `tests/test_r25_stale_index.py`
_(absent at head)_
