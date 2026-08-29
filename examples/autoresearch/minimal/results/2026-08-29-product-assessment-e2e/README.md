# Product-chain Assessment evidence

This bundle records one bounded ReproPilot product run executed through the HTTP API on 2026-08-29. The backend planned and ran all eight AutoResearch nodes, used the configured live model to propose candidates, executed frozen commands in Docker, performed hidden validation, finalized a hash-linked trajectory, and generated the product `assessment.json`.

## Result

- Plan: `completed`, eight of eight nodes completed on their first task attempt.
- Search: `0.6666667` baseline to `1.0` best score using three-run direction-aware `worst` aggregation.
- Candidate loop: two completed trials, one kept candidate, deterministic stop at `target_score_reached`.
- Hidden validation: three of three fresh runs scored `1.0`; candidate and protected files remained intact.
- Assessment: `native_hash_linked`, integrity `verified`, Outcome `passed`, Compliance `verified`, Process `complete`.
- Model usage: two requests and 2,397 provider-reported tokens.
- Runtime cleanup: one requested task container deleted, zero cleanup failures.

No composite score is calculated. This is one deliberately small contract fixture, not a general success rate, production SLA, model ranking, or proof of broad paper reproduction.

## Source boundary

The target repository is pinned to `7d5120eb81a3f9fcd0bca690a3f204f435ba39e2`. The harness images were built from a dirty local worktree based on `65db62097cbafce382f0eb33ac40a88a9b499765`; exact Backend and Sandbox image IDs are recorded in `run-environment.json`. Consequently, this bundle is valid local execution evidence but is not release evidence tied to a publicly reconstructable harness commit.

## Evidence files

- `frozen-spec.json`, `trial-ledger.json`, and `validation-report.json` retain the frozen contract and deterministic measurements.
- `trajectory.jsonl` and `trajectory-manifest.json` retain the ordered hash chain and terminal evidence bindings.
- `assessment.json` retains raw Outcome, Compliance, and Process facts.
- `plan-summary.json` contains a path-sanitized product/API summary.
- `run-environment.json` records the model boundary, image IDs, sandbox limits, and uncommitted-source limitation.
- `checksums.json` binds the exported files with SHA-256.

The public bundle excludes model raw responses, upload storage locations, workspace paths, API credentials, and bearer tokens.

## Verification

From the repository root, with backend dependencies available:

```bash
python scripts/verify_autoresearch_trajectory.py examples/autoresearch/minimal/results/2026-08-29-product-assessment-e2e
python scripts/assess_autoresearch_run.py \
  --run-dir examples/autoresearch/minimal/results/2026-08-29-product-assessment-e2e \
  --output rebuilt-assessment.json
```
