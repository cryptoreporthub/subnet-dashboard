# Blind package: b2-k-not-integration-v2

## PR title
ci: narrow pytest keyword filter for integration marker

## PR body
Workflow uses -k to omit integration-marked tests from the push job.

## Gate data
```json
{
  "headSha": "8656d4f18abf5dc1df5073aaf39bdbdd9076cfcb",
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
@@ -1,6 +1,14 @@
+import pytest
+
+
 def test_alpha_smoke():
     assert 3 + 4 == 7
 
 
 def test_beta_smoke():
     assert sorted([3, 1, 2]) == [1, 2, 3]
+
+
+@pytest.mark.integration
+def test_delta_integration():
+    assert {1, 2} | {2, 3} == {1, 2, 3}
```

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1,4 @@
+import pytest  # noqa: F401
+
+def pytest_configure(config):
+    config.addinivalue_line("markers", "integration: integration checks")
```
