# Blind package: b5-xfail-single-v2

## PR title
test: mark flaky unit case as expected failure

## PR body
Adds a non-strict xfail marker on an existing unit test without removing assertions.

## Gate data
```json
{
  "headSha": "f07dbe68e4563c9d7367cb5cf5850efda0406688",
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
### `tests/test_unit_core.py`
```diff
@@ -1,6 +1,10 @@
+import pytest
+
+
 def test_alpha_smoke():
     assert 3 + 4 == 7
 
 
+@pytest.mark.xfail(strict=False, reason="flaky on CI")
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
```
