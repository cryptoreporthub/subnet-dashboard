# SD-101 `readDiff` byte-identity harness

Runs production `readDiff` (mocked `compareCommitsWithBasehead`) on three inputs:

| Case | Exercises |
|------|-----------|
| `bearer-line` | `bearer=` and `DEFAULT_CLIENT_SECRET=` patch scrubbing |
| `over-budget` | Three 70k-char patches vs `LIMITS.diffChars` |
| `rename` | `previous_filename` + patch |

Expected aggregate at `5d884c47` and `1c3315a2`: sha256 `168d1dbd336b5f612018eea52def981639dc952051d1c09acec792c3cd0b6d09` (70,991 bytes). See [PR #1544 comment 6624123297](https://github.com/cryptoreporthub/subnet-dashboard/pull/1544#issuecomment-6624123297).

## Run

From repo root after checking out the pin under test:

```bash
cd review-gate-bot && npm ci
cp ../exam-artifacts/sd-101/readiff-compare.mjs .
npx tsx readiff-compare.mjs > /tmp/readiff-out.json
sha256sum /tmp/readiff-out.json
wc -c /tmp/readiff-out.json
```

Per-case check:

```bash
jq -c '.["bearer-line"]' /tmp/readiff-out.json | sha256sum
jq -c '.["over-budget"]' /tmp/readiff-out.json | sha256sum
jq -c '.rename' /tmp/readiff-out.json | sha256sum
```

Before/after compare (two clean worktrees at `5d884c476340e2d8d678b20a9039e3a8900a6f10` and `1c3315a28eca6d49d2a3ad630d06d755b334d624`):

```bash
cmp /tmp/readiff-5d884c47.json /tmp/readiff-1c3315a2.json
```
