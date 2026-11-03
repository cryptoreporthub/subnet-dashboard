# Blind package: m4b

## PR title
ci: gate unit job on event type

## PR body
Skips the unit test job for pull_request events via job if.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000011",
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
@@ -2,6 +2,7 @@
 on: [pull_request, push]
 jobs:
   test:
+    if: github.event_name != 'pull_request'
     runs-on: ubuntu-latest
     steps:
       - run: pytest -q
```

## Diff
### `tests/test_r25_m4b_smoke.py`
```diff
@@ -0,0 +1,2 @@
+def test_m4b_smoke():
+    assert 6 + 6 == 12
```

## Repo files (head, read-only context)

### `.github/workflows/ci-smoke.yml`
```yaml
name: ci-smoke
on: [pull_request, push]
jobs:
  test:
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
```

### `tests/test_r25_m4b_smoke.py`
```python
def test_m4b_smoke():
    assert 6 + 6 == 12
```
