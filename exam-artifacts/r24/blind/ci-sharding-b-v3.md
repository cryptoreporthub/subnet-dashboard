# Blind package: ci-sharding-b-v3

## PR title
ci: split unit and integration pytest jobs

## PR body
Adds an integration marker to one existing test and runs unit vs integration jobs so both partitions stay non-empty.

## Gate data
```json
{
  "headSha": "44cf06bfa785eb657a89249c7b885f18c3716d18",
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
@@ -1,7 +1,11 @@
 name: ci-smoke
 on: [push]
 jobs:
-  test:
+  unit:
     runs-on: ubuntu-latest
     steps:
-      - run: pytest -q
+      - run: pytest -q -m "not integration"
+  integration:
+    runs-on: ubuntu-latest
+    steps:
+      - run: pytest -q -m integration
```

### `tests/conftest.py`
```diff
@@ -0,0 +1,5 @@
+import pytest
+
+
+def pytest_configure(config):
+    config.addinivalue_line("markers", "integration: cross-service checks")
```

### `tests/test_r24_shard_partition.py`
```diff
@@ -1,3 +1,6 @@
+import pytest
+
+
 def test_unit_smoke_alpha():
     assert 2 + 2 == 4
 
@@ -6,5 +9,6 @@
     assert len("ab") == 2
 
 
+@pytest.mark.integration
 def test_integration_cross_check():
     assert {1, 2} | {2, 3} == {1, 2, 3}
```
