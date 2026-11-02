# Blind package: ci-sharding-b-v2

## PR title
ci: split unit vs integration jobs

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "c890b0e51bf38fab26cc119a9d5bd73458c8399c",
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
