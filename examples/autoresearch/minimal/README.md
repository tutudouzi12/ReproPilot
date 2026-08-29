# Minimal AutoResearch task package

This directory documents the smallest ReproPilot AutoResearch contract. The checked-in spec pins the public ReproPilot repository revision used for the first live campaign. Upload `candidate.py`, `evaluator.py`, `holdout_evaluator.py`, and `autoresearch.json` in that order so their materialized paths match the frozen contract. When targeting another repository, replace `repository_revision` with that repository's full commit SHA.

The public evaluator is visible during candidate search. `holdout_evaluator.py` is materialized as a protected upload and omitted from the model's proposal context. The Python harness, rather than the model, owns file writes, repeated measurement, Keep/Reject, rollback, integrity checks and final acceptance.

The candidate intentionally starts with a small zero-boundary defect so a live campaign must improve the measured implementation instead of stopping at an already-perfect baseline. The package itself remains a deterministic contract fixture; campaign evidence belongs in the generated ledger and validation report.

## Recorded product-chain run

The [2026-08-29 product Assessment evidence bundle](results/2026-08-29-product-assessment-e2e/) records one run submitted through the HTTP API and completed across all eight DAG nodes. A configured live model proposed two candidates; the model-external harness improved the frozen public metric from `0.6666667` to `1.0`, kept one candidate, passed three fresh hidden-validation runs, verified the 26-event trajectory hash chain, and produced Outcome `passed`, Compliance `verified`, and Process `complete` without a composite score.

This is evidence for one deliberately small contract fixture, not a general success rate or model ranking. The run used Backend and Sandbox images built from a dirty local worktree; their exact image IDs and `release_evidence=false` boundary are retained in `run-environment.json`.
