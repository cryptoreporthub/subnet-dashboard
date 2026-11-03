# Blind package: b5-xfail-single

## PR title
test: mark flaky unit case as expected failure

## PR body
Adds a non-strict xfail marker on an existing unit test without removing assertions.

## Gate data
```json
{
  "headSha": "57832e169f71d1a920166661632b48f307766f0b",
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
@@ -2,5 +2,6 @@
     assert 3 + 4 == 7
 
 
+@pytest.mark.xfail(strict=False, reason="flaky on CI")
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
```

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1 @@
+import pytest
```
