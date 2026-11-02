# Blind package: removal-guarded-b

## PR title
refactor: drop census ping helper and bulk universe checks

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "537cd5177ac6c63ac82c2bf7e587cc9b5c1355b0",
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
### `internal/subnet_universe.py`
```diff
@@ -1,2 +0,0 @@
-def _legacy_census_ping() -> int:
-    return 1
```

### `tests/test_subnet_universe.py`
```diff
@@ -1,24 +0,0 @@
-def test_legacy_census_ping():
-    from internal.subnet_universe import _legacy_census_ping
-    assert _legacy_census_ping() == 1
-
-def test_bulk_placeholder_one():
-    assert True
-
-def test_bulk_placeholder_two():
-    assert True
-
-def test_bulk_placeholder_three():
-    assert True
-
-def test_bulk_placeholder_four():
-    assert True
-
-def test_bulk_placeholder_five():
-    assert True
-
-def test_bulk_placeholder_six():
-    assert True
-
-def test_bulk_placeholder_seven():
-    assert True
```
