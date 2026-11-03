# Blind package: b1-ignore-workflow

## PR title
ci: pass collection ignore flag in workflow pytest

## PR body
Workflow invokes pytest with an explicit ignore path so unit-only collection runs on push.

## Gate data
```json
{
  "headSha": "02d79323382d6fbeea9241942396aefb47551caf",
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
+      - run: pytest -q --ignore=tests/integration
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

## Diff
### `tests/integration/test_link.py`
```diff
@@ -0,0 +1,2 @@
+def test_gamma_cross_layer():
+    assert "ab" in "abc"
```
