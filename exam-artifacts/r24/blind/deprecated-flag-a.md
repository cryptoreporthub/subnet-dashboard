# Blind package: deprecated-flag-a

## PR title
chore: remove legacy universe parser flag

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "99db8657c62c2631718b8e18e05171e054b3877f",
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
### `internal/subnet_universe_flags.py`
```diff
@@ -1 +0,0 @@
-USE_LEGACY_UNIVERSE_PARSER = True
```

### `tests/test_subnet_universe_flags.py`
```diff
@@ -1,5 +0,0 @@
-import os
-
-
-def test_legacy_parser_flag_default():
-    assert os.environ.get("USE_LEGACY_UNIVERSE_PARSER", "0") in ("0", "false", "")
```
