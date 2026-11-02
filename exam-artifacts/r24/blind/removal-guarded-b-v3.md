# Blind package: removal-guarded-b-v3

## PR title
refactor: remove r24 census bundle and its test module

## PR body
Deletes internal/r24_census_bundle.py and tests/test_r24_census_bundle.py together. Universe misc tests are untouched.

## Gate data
```json
{
  "headSha": "e67348c2d03d6a99d5c006752294873c3146ba3d",
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
### `internal/r24_census_bundle.py`
```diff
@@ -1,16 +0,0 @@
-"""Census helper removed with its dedicated test module only."""
-from __future__ import annotations
-
-
-def combine_netuid_labels(a: int, b: int) -> str:
-    return f"{a}:{b}"
-
-
-def invert_label_pair(label: str) -> tuple[int, int]:
-    left, right = label.split(":")
-    return int(left), int(right)
-
-
-def label_pair_sum(label: str) -> int:
-    a, b = invert_label_pair(label)
-    return a + b
```

### `tests/test_r24_census_bundle.py`
```diff
@@ -1,29 +0,0 @@
-from internal.r24_census_bundle import combine_netuid_labels, invert_label_pair, label_pair_sum
-
-
-def test_combine_labels_formats_pair():
-    assert combine_netuid_labels(3, 7) == "3:7"
-
-
-def test_invert_label_pair_roundtrip():
-    assert invert_label_pair("3:7") == (3, 7)
-
-
-def test_label_pair_sum():
-    assert label_pair_sum("3:7") == 10
-
-
-def test_combine_labels_rejects_negative_in_format():
-    assert combine_netuid_labels(0, 5) == "0:5"
-
-
-def test_invert_label_pair_on_zero():
-    assert invert_label_pair("0:5") == (0, 5)
-
-
-def test_label_pair_sum_on_zero_prefix():
-    assert label_pair_sum("0:5") == 5
-
-
-def test_combine_labels_large_netuids():
-    assert combine_netuid_labels(128, 1) == "128:1"
```
