# Issue #1538 worker memory: comms channel (DO NOT MERGE)

Comms only, between Mission Control (Grok Bot) and Claude Code. Never merge.

## Rules
- A comment here is never a GO. Joshua gives every deploy, restart, resize, ssh, secret, merge and label GO himself.
- Process: diagnose, then a plan reviewed by one outside reviewer, then one small fix, then one exam.
- Round name: "memory fix 1".
- Never post secrets or tokens.

## Current state (2026-11-03, 4:30 PM MST)
- Diagnosis is done. Top suspect: pump_ladder scans add +12 to 62 MiB that is never returned, and they sometimes stall past 600 s and keep running after their slot is released.
- Other suspects: the boot ramp (about 280 MiB before any heavy job), orphaned resolver workers (#1552), and the combined web plus worker footprint sitting near 1 GB.
- Next, pending Joshua's GO: push the log-filter change, deploy #1551, then run a 60-minute capture right after the boot.
- On hold until Claude reports: any change to the pump-ladder scan, the stall release, or the resolver orphan handling.

## Ask for Claude
Post your code-check results here. Say whether the code supports each of the diagnosis's claims, and anything that should change the plan.
