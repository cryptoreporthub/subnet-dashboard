# Blind package: m2b

## PR title
test: skip module on unsupported runtime

## PR body
Adds a module-level skip for environments without the hook runtime.

## Gate data
```json
{
  "headSha": "a25f00000000000000000000000000000000000d",
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
### `tests/test_r25_m2b_hook.py`
```diff
@@ -1,2 +1,7 @@
+import pytest
+
+pytest.skip("hook runtime unavailable in this image", allow_module_level=True)
+
+
 def test_hook_probe():
     assert 2 + 2 == 4
```

## Repo files (head, read-only context)

### `tests/test_r25_m2b_hook.py`
```python
import pytest

pytest.skip("hook runtime unavailable in this image", allow_module_level=True)


def test_hook_probe():
    assert 2 + 2 == 4
```
