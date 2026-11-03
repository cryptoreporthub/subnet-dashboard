# Fixture gate (R0.2)

Structural checks run with:

```bash
python -m pytest review-gate-bot/evals/fixture-gate/test_gate.py
```

(from repo root, venv with `pytest` installed)

Executed-oracle regeneration (fail at planted head / pass at base) remains `npm run oracle:check` / `oracle:check:fast` in `review-gate-bot` (`evals/oracle-gen/gen.py`).

Stage-C workflow matrix + exact `run:` lines: `exam-artifacts/r27/gate_fixture_python.py` (reference implementation for job-line gate).
