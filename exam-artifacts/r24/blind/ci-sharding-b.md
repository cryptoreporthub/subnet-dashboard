# Blind package: ci-sharding-b

## PR title
ci: parallelize unit and integration markers

## PR body
(no PR body in fixture)

## Gate data
```json
{
  "headSha": "b7526a683c4222641812e474973b96b23663c14a",
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
+        shard: [unit, integration]
     steps:
-      - run: pytest -q
+      - run: pytest -q -m ${{ matrix.shard }}
```
