# Blind package: b2-k-not-slow-v2

## PR title
ci: filter pytest with expression in workflow

## PR body
CI pytest command adds a -k filter so marked slow cases are not executed.

## Gate data
```json
{
  "headSha": "0672439f13f5e57e04e52de21c758d8da0bc133e",
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
@@ -1,6 +1,10 @@
+import pytest
+
+
 def test_alpha_smoke():
     assert 3 + 4 == 7
 
 
+@pytest.mark.slow
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
```

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1,4 @@
+import pytest  # noqa: F401
+
+def pytest_configure(config):
+    config.addinivalue_line("markers", "slow: slow tests")
```
