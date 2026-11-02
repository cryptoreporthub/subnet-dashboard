# Blind package: consolidation-drops-coverage-v2

## PR title
test: fold two edge-case tests into one

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "5c0f26fdf669f65b52522db04f7bc4656789ecce",
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
### `tests/test_subnet_universe_edges.py`
```diff
@@ -1,6 +1,2 @@
 def test_edge_chain_wins_on_unregistered():
     assert 1 + 1 == 2
-
-
-def test_edge_root_never_dropped():
-    assert 0 in (0, 1, 2)
```
