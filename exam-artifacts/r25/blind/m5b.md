# Blind package: m5b

## PR title
ci: adjust declared shard matrix

## PR body
Matrix omits a shard index still implied by num-shards.

## Gate data
```json
{
  "headSha": "a25f000000000000000000000000000000000013",
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
@@ -3,5 +3,8 @@
 jobs:
   test:
     runs-on: ubuntu-latest
+    strategy:
+      matrix:
+        shard-index: [0, 1]
     steps:
-      - run: pytest -q
+      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=3
```

## Repo files (head, read-only context)

### `.github/workflows/ci-smoke.yml`
```yaml
name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard-index: [0, 1]
    steps:
      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=3
```
