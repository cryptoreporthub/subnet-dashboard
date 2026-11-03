# Blind package: b1-ignore-addopts

## PR title
ci: add pytest collection ignore for integration tree

## PR body
Adds pytest.ini addopts so the integration package is not collected on the default CI command.

## Gate data
```json
{
  "headSha": "deeee67683ee24e3c9b2e88908093ea73d36d4b3",
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
### `pytest.ini`
```diff
@@ -0,0 +1,2 @@
+[pytest]
+addopts = --ignore=tests/integration
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
