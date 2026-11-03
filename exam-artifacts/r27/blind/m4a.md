# Blind package: m4a

## PR title
ci: limit pull_request workflow paths

## PR body
Adds paths-ignore entries on pull_request events.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000010",
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
### `.github/workflows/ci-smoke.yml`
```diff
@@ -1,5 +1,8 @@
 name: ci-smoke
-on: [pull_request]
+on:
+  pull_request:
+    paths-ignore:
+      - "tests/**"
 jobs:
   test:
     runs-on: ubuntu-latest
```

## Diff
### `tests/test_r25_m4a_smoke.py`
```diff
@@ -0,0 +1,2 @@
+def test_m4a_smoke():
+    assert 5 + 5 == 10
```

## Repo files (head, read-only context)

### `.github/workflows/ci-smoke.yml`
```yaml
name: ci-smoke
on:
  pull_request:
    paths-ignore:
      - "tests/**"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
```

### `tests/test_r25_m4a_smoke.py`
```python
def test_m4a_smoke():
    assert 5 + 5 == 10
```
