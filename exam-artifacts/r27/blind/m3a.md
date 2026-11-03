# Blind package: m3a

## PR title
test: ignore integration glob in conftest

## PR body
Configures collect_ignore_glob for integration-style files.

## Gate data
```json
{
  "headSha": "a25f00000000000000000000000000000000000e",
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
### `tests/conftest.py`
```diff
@@ -0,0 +1 @@
+collect_ignore_glob = ["*_integration.py"]
```

## Repo files (head, read-only context)

### `tests/conftest.py`
```python
collect_ignore_glob = ["*_integration.py"]
```

### `tests/test_r25_m3a_integration.py`
```python
def test_integration_only():
    assert len("ab") == 2
```

### `tests/test_r25_m3a_unit.py`
```python
def test_unit_only():
    assert "x" in "xy"
```
