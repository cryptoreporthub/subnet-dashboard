# R1 pack B

- **Scope:** 48 oracle fixtures (`r1b-*`) in `review-gate-bot/evals/fixtures/`, built by `evals/oracle-gen/pack_b_gen.py`.
- **Families:** F1 guard relax, F2 falsy netuid, F3 logic + unmeasured-perf claim shape, F4 suite shrink/skip, 12 clean PASS controls, redaction stratum, generalization across module paths.
- **Regen:** from `review-gate-bot`: `npm run oracle:regen -- --python /path/to/venv/bin/python` (venv needs `requirements.txt` + pytest).
- **Gate:** `npm run fixture-gate` — log mirror at `exam-artifacts/r1/pack-b/fixture-gate.log`.
- **Inventory:** `fixture-table.md`; redaction design notes in `redaction-stratum-table.md`.
- **RUN gate:** no model eval until RUN-READY-R1PRE.
