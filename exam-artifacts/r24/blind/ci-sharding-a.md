# Blind package: ci-sharding-a

## PR title
ci: shard pytest across two runners

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "a3baca992740e1b3d4211bf07c48f6a522e73233",
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
+        shard: [1, 2]
     steps:
-      - run: pytest -q
+      - run: pytest -q --shard-id=${{ matrix.shard }} --num-shards=2
```
