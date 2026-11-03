# Fixture gate (R0.2)

One fail-closed command (from `review-gate-bot/`):

```bash
npm run fixture-gate
```

Runs, in order: structural `python -m pytest evals/fixture-gate/test_gate.py`, known-bad rejection tests (`test_known_bad.py`), `oracle-gen --check --skip-behavior` (legacy hard-* only; `hard-r24-*` scoped out), and when present `exam-artifacts/r27/gate_fixture_python.py` (exact workflow job lines + execution).

Structural checks alone:

```bash
python -m pytest review-gate-bot/evals/fixture-gate/test_gate.py
```

(from repo root, venv with `pytest` installed)

Executed-oracle regeneration (fail at planted head / pass at base) remains `npm run oracle:check` / `oracle:check:fast` (`evals/oracle-gen/gen.py`).

Stage-C workflow matrix + exact `run:` lines reference: `exam-artifacts/r27/gate_fixture_python.py`.
