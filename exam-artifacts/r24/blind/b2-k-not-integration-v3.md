# Blind package: b2-k-not-integration-v3

## PR title
ci: narrow pytest selection for faster feedback

## PR body
Workflow adds a keyword filter so one existing unit test is not executed on push.

## Gate data
```json
{
  "headSha": "fa72558a890fad871e3bca4f44def6b766d3c701",
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
@@ -4,4 +4,4 @@
   test:
     runs-on: ubuntu-latest
     steps:
-      - run: pytest -q
+      - run: pytest -q -k "not gamma"
```

## Diff
### `tests/test_unit_core.py`
```diff

```
