# CONSTITUTION FROZEN

**Declared:** 2026-09-19T20:06Z  
**By:** Joshua (explicit Go) via Mission Control  
**PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1294  
**Branch:** docs/arch-epistemics-pass0-skeleton  
**Pin:** c9449d6490231373748f19f299ed19d423a1c971

## This freeze locks

1. **Fetch ladder:** raw → api → mc_paste; bundles MUST carry `fetch_method`.
2. **MC router:** strip prose/fences → first JSON object → schema validate → file to Ledger only if valid.
3. **Smoke anchor:** `server.py` **line 628** = `TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))` (context 626–630; line 633 is not the lock).

Edits to CONSTITUTION.md require a **new** explicit freeze Go.
