# lock-6 sent system prompt extraction

Extracted from agent runner `store.db` (`blobs` table, `role=system` JSON). Not from `capture_eval_system_prompt`.

## Verdict vs helper target `6637087582c794c1011219dd51951b4a9e829d3f24507a037a15c0570557d1fe`

| Run | Session | Bytes | SHA-256 | vs helper |
|-----|---------|-------|---------|-----------|
| POST lock-6 | ses_e24eebf4771c839c969173ce | 7882 | `620baecc7515c08d4b08a5e761d0d340062ee0137a7f6cdbfb946bd7ad4742ab` | **MISMATCH** |
| PRE live | ses_e396d3ad92d6c19a55069382 | 7335 | `4fbf87011cacd116f03d4659b30f05a456bb2971f53e3ed86462285847b3bfba` | **MISMATCH** |

## Files

- `post-system-prompt.txt` / `post-system-prompt.sha256`
- `pre-system-prompt.txt` / `pre-system-prompt.sha256`
- `bars-lock-evidence.md`

## Locations searched (no system bytes)

- eval artifact JSON (review-gate-hard/ci-skipped-tests-clean-comparison/1.json): no systemPrompt field
- session events.ndjson: event types session/turn/message/reasoning only; no system message event
- agent-transcripts jsonl: user/assistant turns only; no system role line
- eval summary.json / results.jsonl: no prompt fields
