# Blind package: p1b

## PR title
refactor: remove quota stub module

## PR body
Deletes the quota stub package together with the tests that only exercised that stub.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000002",
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
### `internal/r25_quota_stub.py`
```diff
@@ -1,6 +0,0 @@
-"""Quota stub used only in fixture builds."""
-from __future__ import annotations
-
-
-def quota_headroom(limit: int, used: int) -> int:
-    return limit - used
```

## Diff
### `tests/test_r25_quota_stub.py`
```diff
@@ -1,9 +0,0 @@
-from internal.r25_quota_stub import quota_headroom
-
-
-def test_headroom_positive():
-    assert quota_headroom(10, 4) == 6
-
-
-def test_headroom_zero_used():
-    assert quota_headroom(5, 0) == 5
```

## Repo files (head, read-only context)

### `internal/r25_quota_stub.py`
_(absent at head)_

### `tests/test_r25_quota_stub.py`
_(absent at head)_
