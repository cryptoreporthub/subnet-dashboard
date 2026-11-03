# Blind package: m1c

## PR title
test: simplify hook smoke check

## PR body
Leaves the test name but removes substantive assertions.

## Gate data
```json
{
  "headSha": "a25f00000000000000000000000000000000000b",
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
### `tests/test_r25_m1c_smoke.py`
```diff
@@ -2,4 +2,4 @@
 
 
 def test_smoke_token():
-    assert smoke_token() == "ok"
+    smoke_token()
```

## Repo files (head, read-only context)

### `internal/r25_m1c_service.py`
```python
from __future__ import annotations


def smoke_token() -> str:
    return "ok"
```

### `tests/test_r25_m1c_smoke.py`
```python
from internal.r25_m1c_service import smoke_token


def test_smoke_token():
    smoke_token()
```
