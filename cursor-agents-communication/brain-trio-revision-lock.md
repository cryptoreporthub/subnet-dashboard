# Brain Trio Revision — Living Focus · Mindmap · Living Brain

**Status:** LOCK ACTIVE — W0-A…F implemented on `cursor/brain-trio-revision-1d2f` (babysit → merge)  
**Updated:** 2026-07-27  
**Branch:** `cursor/brain-trio-revision-1d2f`  
**Baseline:** `main` @ `f7aadc0` (#542 LB-12)  
**DITTO_REVIEW:** `e32a6fae`

```
VERDICT: CONDITIONAL — W0-A…F coded; await merge + prod smoke
DECISIONS:
- Honesty before features (RF-2 on Proof)
- One story spine (hydrate home cause chain)
- Graph skips hold dispositions; cap ~48 by degree
- Mindmap+trail on brain spine (not Market drawer)
- Kill LB-10 SN1/2/3 stub
NON-GOALS: confidence/LONG (#491), Telegram, dual portfolio, full money-flow
```

## Wave status

| Wave | Status | What shipped |
|------|--------|--------------|
| W0-A Proof RF-2 | ✅ | Proof/KPI/track record gated on `trust_banner.ready`; banner visible when blocked |
| W0-B Focus truth | ✅ | `trailEvidence`, pickLearnEvent, weight `--pct`, Open subnet, WATCH badge, one dissent |
| W0-C Story spine | ✅ | `story_path_ui` hydrates home cause chain; weight step `done` when weights exist |
| W0-D Graph taste | ✅ | Skip unscoped holds; node cap 48; human detail line |
| W0-E Placement | ✅ | Mindmap + trail after Proof band |
| W0-F Stub + board | ✅ | Honest-empty brain recs; summary fluff removed |
| DONE | 🔄 | Merge + prod smoke |

## Verify

```bash
PYTHONPATH=/workspace .venv/bin/pytest tests/test_proof_rf2.py tests/test_living_brain.py \
  tests/test_phase_g_mindmap_graph.py tests/test_endpoint_contract.py -q
```

## Definition of DONE

- [x] W0-A…F implemented
- [ ] Merged to `main`
- [ ] Prod smoke: proof quiet if not ready; graph ≤48; mindmap on spine
- [ ] Lock → Status: DONE; board Active cleared
