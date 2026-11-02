# Blind package: ci-sharding-a-v2

## PR title
ci: shard pytest with pytest-shard (0/1 of 2)

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "b2d9242aead784db8dd7beaa3411e558a7187f35",
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
@@ -3,5 +3,9 @@
 jobs:
   test:
     runs-on: ubuntu-latest
+    strategy:
+      matrix:
+        shard-index: [0, 1]
     steps:
-      - run: pytest -q
+      - run: pip install pytest-shard
+      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=2
```
