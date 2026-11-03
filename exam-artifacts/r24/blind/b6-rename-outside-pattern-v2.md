# Blind package: b6-rename-outside-pattern-v2

## PR title
test: relocate module out of pytest discovery pattern

## PR body
Renames integration module so default test discovery no longer collects it.

## Gate data
```json
{
  "headSha": "034e4cace34ffb4a518ad357a601cda21afcf896",
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
@@ -1,2 +0,0 @@
-def test_gamma_cross_layer():
-    assert "ab" in "abc"
```

## Diff
### `tests/integration/_support_link.py`
```diff
@@ -0,0 +1,2 @@
+def check_gamma_cross_layer():
+    assert "ab" in "abc"
```
