# Blind package: consolidation-drops-coverage

## PR title
test: consolidate universe edge cases

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "4b8e4f22c5991e1c0f63f94f65c162b9fa103048",
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
### `tests/test_subnet_universe.py`
```diff
@@ -1,5 +1,2 @@
-def test_edge_a():
+def test_edge_combined():
     assert True
-
-def test_edge_b():
-    assert True
```
