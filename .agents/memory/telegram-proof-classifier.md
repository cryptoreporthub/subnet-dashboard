---
name: Telegram proof classifier
description: Durable grading policy for Telegram call hit/miss/neutral — the decision that must stay consistent everywhere.
---

# Telegram proof grading policy

Telegram caller leaderboard, proof band, and feed proof cards MUST agree on the
exact same classification, so grading is centralised in one classifier module
under `internal/message_intel/` and consumed by leaderboard, band, receipts, and
feed enrichment alike. Reimplementing classification anywhere else causes
leaderboard/band/card drift. Verify changes against `tests/test_telegram_proof_contract.py`.

## Durable decisions

- **Direction resolution mirrors the locked `self_learning._is_correct_prediction`
  precedence, up-branch first:** a bull verdict *or* up direction → up; a bear
  verdict *or* down direction → down. A row with no direction signal at all is
  unqualified (chatter), never a prediction.
- **up+stable is shown as NEUTRAL, excluded from accuracy** — but hit still means
  locked-correct. This is presentation, not re-grading; boolean hit↔correct
  parity with the locked rule must be preserved and tested.
- **up → hit on {pump, mild_pump} or pump_pct_max > 2.0** (transient-pump
  confirmation); down → hit on {dump, mild_dump}; flat → hit on stable.
- **Accuracy = hit/(hit+miss)**; neutral and all engagement data (reactions,
  views) are excluded. Never count neutral/unqualified chatter as a prediction.

**Why:** Locked rule punishes flat markets as wrong calls, which reads as unfair
noise on a public caller board; a neutral bucket plus exclusion from accuracy is
more honest while keeping hit/miss parity with the authoritative rule.

**How to apply:** any outcome/eligibility change stays in that classifier module
and must keep hit↔locked-correct parity; add regression tests there, not in the
rollup/engine/route layer.
