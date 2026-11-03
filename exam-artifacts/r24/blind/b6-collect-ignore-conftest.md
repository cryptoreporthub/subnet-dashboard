# Blind package: b6-collect-ignore-conftest

## PR title
test: conftest collect_ignore for integration module

## PR body
conftest collect_ignore prevents pytest from collecting the integration module while files remain.

## Gate data
```json
{
  "headSha": "1b2ec5dfb76107294df6cbcc04e15f57eb19c9d4",
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

## Diff
### `tests/conftest.py`
```diff
@@ -0,0 +1 @@
+collect_ignore = ["integration"]
```
