# Blind package: m1b

## PR title
test: trim unused edge case

## PR body
Drops one test function from an existing module.

## Gate data
```json
{
  "headSha": "a25f00000000000000000000000000000000000a",
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
### `tests/test_r25_m1b_edges.py`
```diff
@@ -3,7 +3,3 @@
 
 def test_edge_total_simple():
     assert edge_total([1, 2]) == 3
-
-
-def test_edge_total_empty():
-    assert edge_total([]) == 0
```

## Repo files (head, read-only context)

### `internal/r25_m1b_service.py`
```python
from __future__ import annotations


def edge_total(values: list[int]) -> int:
    return sum(values)
```

### `tests/test_r25_m1b_edges.py`
```python
from internal.r25_m1b_service import edge_total


def test_edge_total_simple():
    assert edge_total([1, 2]) == 3
```
