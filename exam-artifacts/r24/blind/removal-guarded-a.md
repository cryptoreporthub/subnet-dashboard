# Blind package: removal-guarded-a

## PR title
chore: remove legacy subnet probe shim

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "ef2c81e1e1089a9c0873a7cfce6b2b978d1c1c9e",
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
### `internal/legacy_subnet_probe.py`
```diff
@@ -1,6 +0,0 @@
-"""Legacy subnet probe helpers (scheduled for removal with v2 census)."""
-from __future__ import annotations
-
-
-def probe_once(netuid: int) -> bool:
-    return netuid >= 0
```

### `tests/test_legacy_subnet_probe.py`
```diff
@@ -1,5 +0,0 @@
-from internal.legacy_subnet_probe import probe_once
-
-
-def test_probe_accepts_non_negative_netuid():
-    assert probe_once(5) is True
```
