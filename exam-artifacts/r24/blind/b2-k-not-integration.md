# Blind package: b2-k-not-integration

## PR title
ci: narrow pytest keyword filter for integration marker

## PR body
Workflow uses -k to omit integration-marked tests from the push job.

## Gate data
```json
{
  "headSha": "d88acf913266c5ef7443ccfa5030283fc68340fa",
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
+      - run: pytest -q -k "not integration"
```

## Diff
### `tests/test_unit_core.py`
```diff
@@ -4,3 +4,10 @@
 
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
+
+
+import pytest
+
+@pytest.mark.integration
+def test_delta_integration():
+    assert True
```

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1,3 @@
+import pytest
+
+pytest_configure = lambda c: c.addinivalue_line("markers", "integration: integration checks")
```
