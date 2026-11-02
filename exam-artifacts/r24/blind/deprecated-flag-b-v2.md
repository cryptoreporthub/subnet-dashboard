# Blind package: deprecated-flag-b-v2

## PR title
chore: drop experimental refresh toggle

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "ca7d91c5030154ea210ecaa64ee5649cb3110899",
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
@@ -1,5 +0,0 @@
-def test_refresh_toggle_enabled():
-    import tomllib
-    from pathlib import Path
-    data = tomllib.loads(Path("config/experimental_refresh.toml").read_bytes())
-    assert data["enabled"] is True
```
