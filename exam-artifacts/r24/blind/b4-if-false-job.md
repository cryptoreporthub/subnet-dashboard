# Blind package: b4-if-false-job

## PR title
ci: gate test job behind always-false condition

## PR body
Test job is guarded by if: false so pytest never runs on push despite workflow remaining present.

## Gate data
```json
{
  "headSha": "18bb7b449fd4ba4d5aad47e7ccd524888b588c81",
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
@@ -2,6 +2,7 @@
 on: [push]
 jobs:
   test:
+    if: false
     runs-on: ubuntu-latest
     steps:
       - run: pytest -q
```

## Diff
### `tests/test_unit_core.py`
```diff
@@ -0,0 +1,6 @@
+def test_alpha_smoke():
+    assert 3 + 4 == 7
+
+
+def test_beta_smoke():
+    assert sorted([3, 1, 2]) == [1, 2, 3]
```
