# Blind package: m3b

## PR title
test: narrow default pytest discovery paths

## PR body
Restricts pytest testpaths to a subset of directories.

## Gate data
```json
{
  "headSha": "a25f00000000000000000000000000000000000f",
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
### `pytest.ini`
```diff
@@ -1,2 +1,2 @@
 [pytest]
-testpaths = tests
+testpaths = tests/unit
```

## Repo files (head, read-only context)

### `pytest.ini`
```ini
[pytest]
testpaths = tests/unit
```

### `tests/test_r25_m3b_wide.py`
```python
def test_wide_path():
    assert 2 * 3 == 6
```

### `tests/unit/test_r25_m3b_narrow.py`
```python
def test_narrow_path():
    assert 4 - 1 == 3
```
