# Blind package: test-deleted-prod-kept

## PR title
test: delete stale universe regression file

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "ab79f2b9f19a4ef6e4d538a3cf74446adf3fc101",
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
### `tests/test_subnet_universe_stale_regression.py`
```diff
@@ -1,3 +0,0 @@
-def test_stale_regression_placeholder():
-    from internal.subnet_universe import STALE_GRACE_SECONDS
-    assert STALE_GRACE_SECONDS > 0
```
