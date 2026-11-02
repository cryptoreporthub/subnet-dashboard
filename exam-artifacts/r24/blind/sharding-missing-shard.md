# Blind package: sharding-missing-shard

## PR title
ci: start pytest sharding rollout

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "a2ad7be1daf58e3db271a94df87e0994248c7423",
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
+        shard: [1]
     steps:
-      - run: pytest -q
+      - run: pytest -q --shard-id=1 --num-shards=2
```
