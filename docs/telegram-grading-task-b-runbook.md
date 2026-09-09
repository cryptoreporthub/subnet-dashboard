# Telegram grading Task B runbook

This is an operations runbook, not a deploy authorization. Do not merge or
deploy from this document.

## Safe order

1. Preserve the current week before changing the message-intel store:

   ```bash
   python scripts/reset_message_intel.py --keep-week --dry-run
   ```

2. Deploy and validate the C-series grading changes **before** any destructive
   wipe. Confirm the deployed revision, `/health`, and the Telegram grading
   contract tests.
3. If a clean epoch is explicitly approved, run the selected reset mode. Keep
   the week by default:

   ```bash
   python scripts/reset_message_intel.py --keep-week --clean-alerts
   ```

4. Use `--full` only with explicit approval. A full wipe removes message
   history, author reliability, and pattern-correlation evidence.
5. After reset, verify that the listener is refilling and that pending calls
   remain pending until their own 1h, 4h, and 24h observations exist.

## Evidence rules

- `price_1h`, `price_4h`, and `price_24h` are independent subnet-price
  observations; a later resolver tick must not replace an earlier observation.
- `correct_1h`, `correct_4h`, and `correct_24h` are separate grades. Missing
  observations are pending, not a failed grade.
- Accuracy excludes neutral and pending calls and never uses reactions, views,
  forwards, or TAO-only chatter.
- Every gate needs a named condition: green means the focused grading tests
  pass and the deployed revision is identified; blocked means either evidence
  is missing or any horizon is being graded from another horizon's price.

## Operator discipline

Before accepting a claim, cite its commit, test output, or runtime log. Treat
missing evidence as `unknown`, distinguish containment from root-cause repair,
and name any fixed/environmental input that could hide the cause. No reset or
deploy is harmless merely because it is described as read-only.
