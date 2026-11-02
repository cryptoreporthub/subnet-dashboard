# Blind package: tests-moved-b

## PR title
test: split sanity checks into package layout

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "e6978947b7a3d70c215c6b5ce71af6dfdb277722",
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
### `tests/test_subnet_sanity.py`
```diff
@@ -1,2 +0,0 @@
-def test_moved_happy_path():
-    assert 2 + 2 == 4
```

### `tests/sanity/test_core.py`
```diff
@@ -0,0 +1,2 @@
+def test_moved_happy_path():
+    assert 2 + 2 == 4
```
