# Blind package: deprecated-flag-b

## PR title
chore: drop experimental refresh toggle

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "3e548e03120c4571a16fb1fb2eb6bf2c0f4b658c",
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
### `config/experimental_refresh.toml`
```diff
@@ -1 +0,0 @@
-enabled = true
```

### `tests/test_experimental_refresh_config.py`
```diff
@@ -1,2 +0,0 @@
-def test_refresh_toggle_enabled():
-    assert True
```
