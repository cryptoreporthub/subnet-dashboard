---
description: Use on every pull request review. The owner's standing rules for subnet-dashboard, and what each one means for a diff.
---

# Owner rules

These are Joshua's requirements, verbatim. Judge the diff against each one that
its files touch. Do not restate them as preferences, and do not relax them
because a test passes.

## 1. Picks readers serve only complete snapshots, and picks never go blank

A reader must not serve a partially written snapshot. A missing or partial
snapshot must never turn the picks surface blank: serve the last complete
snapshot instead.

Check: what happens when the producer is mid-write, or has never run on a fresh
volume? Blank is a regression, not an empty state.

Check the reader's own acceptance test, not only the writer. A persisted snapshot
with no members (empty or zero `netuids`) is not a complete snapshot, so a reader
that loads one and replaces the serving snapshot has turned a good snapshot into a
blank one. "The worker never publishes an empty snapshot" is a second layer, not a
reason to let the reader trust the file: a file can be truncated, hand-edited or left
by an older build. A fallback on one accessor (for example an emergency list) does
not excuse the other accessors that serve the snapshot as it is.

## 2. The chain wins over TaoMarketCap

Chain membership is authoritative. A subnet the chain no longer lists leaves
`expected_netuids` **immediately**, and its row keeps a **48h grace** before it
is dropped.

TaoMarketCap listing a subnet the chain does not is not evidence for membership
(that is #1516's case: SN7 off-chain but TMC-listed still leaves `expected` at
127 and keeps the row).

## 3. Netuid 0 is never removed. The universe is 128

Netuid 0 is a valid subnet and must survive every prune path. The universe size
is 128; a diff that changes 127 to 128, or 128 to anything else, needs a
measured reason.

Two numbers sound alike and are not the same: the **universe is 128 members**
(0 to 127). `MAX_NETUIDS = 200` in `subnet_universe.py` is how many candidate
netuids the probe scans, not how many members there are. When you bound the size
of anything built from membership, say 128; never cite 200 as the universe.

## 4. A failed cycle stays fail-closed. Only the owner worker produces

A worker that is not the owner must refuse to produce. A failed cycle must not
be papered over by a non-owner writing a fresh artifact: that converts a visible
failure into a silent one.

Watch for a worker that receives `not_owner` and retries forever, or exits and
restarts. That is a crash loop built out of a guard.

## 5. #1461 is do-not-push

Do not push to #1461, do not push its branch, and do not treat its state as
evidence for anything else.

## Applying these

Name the rule number in each finding. A finding outside these rules is still a
finding; say so and give it its own severity.
