# Blind package: m1a

## PR title
test: drop stale regression file

## PR body
Removes a regression test module; service code is unchanged.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000009",
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
### `tests/test_r25_m1a_hook.py`
```diff
@@ -1,5 +0,0 @@
-from internal.r25_m1a_service import hook_value
-
-
-def test_hook_value_stable():
-    assert hook_value() == 42
```

## Repo files (head, read-only context)

### `internal/r25_m1a_service.py`
```python
from __future__ import annotations


def hook_value() -> int:
    return 42
```

### `tests/test_r25_m1a_hook.py`
_(absent at head)_
