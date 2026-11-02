# Blind package: tests-moved-a

## PR title
test: relocate subnet sanity checks file

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "9ea8deba8a21bf6e23ba90f0466a59c8e878b2a8",
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
### `tests/test_subnet_sanity_checks.py`
```diff
@@ -1,2 +0,0 @@
-def test_moved_happy_path():
-    assert 2 + 2 == 4
```

### `tests/test_subnet_sanity.py`
```diff
@@ -0,0 +1,2 @@
+def test_moved_happy_path():
+    assert 2 + 2 == 4
```
