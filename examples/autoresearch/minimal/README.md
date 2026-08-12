# Minimal AutoResearch task package

This directory documents the smallest ReproPilot AutoResearch contract. The checked-in spec pins the public ReproPilot repository revision used for the first live campaign. Upload `candidate.py`, `evaluator.py`, `holdout_evaluator.py`, and `autoresearch.json` in that order so their materialized paths match the frozen contract. When targeting another repository, replace `repository_revision` with that repository's full commit SHA.

The public evaluator is visible during candidate search. `holdout_evaluator.py` is materialized as a protected upload and omitted from the model's proposal context. The Python harness, rather than the model, owns file writes, repeated measurement, Keep/Reject, rollback, integrity checks and final acceptance.

The candidate intentionally starts with a small zero-boundary defect so a live campaign must improve the measured implementation instead of stopping at an already-perfect baseline. The package itself remains a deterministic contract fixture; campaign evidence belongs in the generated ledger and validation report.
