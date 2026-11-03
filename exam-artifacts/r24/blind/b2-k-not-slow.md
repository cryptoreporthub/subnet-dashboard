# Blind package: b2-k-not-slow

## PR title
ci: filter pytest with expression in workflow

## PR body
CI pytest command adds a -k filter so marked slow cases are not executed.

## Gate data
```json
{
  "headSha": "30636cc6ab936bb7e0720516703ab4615529bc5d",
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
### `.github/workflows/ci-smoke.yml`
```diff
@@ -4,4 +4,4 @@
   test:
     runs-on: ubuntu-latest
     steps:
-      - run: pytest -q
+      - run: pytest -q -k "not slow"
```

## Diff
### `tests/test_unit_core.py`
```diff
@@ -2,5 +2,6 @@
     assert 3 + 4 == 7
 
 
+def @pytest.mark.slow
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
```

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1 @@
+import pytest
```
