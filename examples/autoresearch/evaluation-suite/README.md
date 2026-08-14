# AutoResearch evaluation scenario suite

This suite turns AutoResearch governance claims into seven fixed, repeatable tasks. Every task materializes a candidate, frozen public and hidden cases, a full repository revision, allowed commands, and an expected terminal outcome. The runner retains the baseline, trial decisions, validation report, model usage, cost basis, final candidate, hashes, failures, and stated evidence boundary.

## Scenario matrix

| Scenario | Expected outcome | What it checks | Proposer |
| --- | --- | --- | --- |
| `zero-boundary-success` | `validation_passed` | Public improvement generalizes to hidden cases | Scripted or live model |
| `identifier-normalization-success` | `validation_passed` | A second independent repair generalizes | Scripted or live model |
| `unauthorized-patch-rejected` | `candidate_rejected_contract` | Protected evaluators cannot be patched | Scripted fault injection |
| `syntax-guard-rejected` | `candidate_rejected_guard` | Invalid code fails before metric evaluation | Scripted fault injection |
| `evaluator-timeout-rejected` | `candidate_rejected_timeout` | A blocking candidate is rejected and rolled back | Scripted fault injection |
| `hidden-holdout-failed` | `hidden_validation_failed` | Public gain without hidden gain is not accepted | Scripted fault injection |
| `protected-mutation-aborts` | `integrity_abort` | Protected-file drift aborts and restores the run | Scripted fault injection |

Scripted fault injection validates deterministic Harness behavior. It must not be presented as evidence that a model naturally produces each failure. The two live-capable scenarios evaluate an actual configured model, but they remain small code tasks rather than a repository-scale repair benchmark.

## Deterministic run

From the repository root:

```powershell
py -3.11 .\scripts\run_evaluation_scenarios.py `
  --mode scripted `
  --output data\evaluation-results\scripted-run
```

CI runs all seven deterministic scenarios. A mismatch between the expected and observed outcome fails the command.

## Bounded live-model run

The runner can read the ignored `backend.env` without printing secrets. Only the two scenarios marked `allow_live_model` call the provider; all failure-injection scenarios remain scripted.

```powershell
py -3.11 .\scripts\run_evaluation_scenarios.py `
  --mode live `
  --env-file backend.env `
  --max-live-requests-per-scenario 2 `
  --output data\evaluation-results\live-run
```

Provider-reported prompt, completion, and total tokens are always retained. Monetary cost is calculated only when current billing rates are supplied explicitly:

```powershell
py -3.11 .\scripts\run_evaluation_scenarios.py `
  --mode live `
  --env-file backend.env `
  --input-cost-per-million <verified-input-rate> `
  --output-cost-per-million <verified-output-rate> `
  --currency USD `
  --pricing-source <provider-billing-page-url> `
  --pricing-tier <applicable-token-tier> `
  --pricing-verified-at <YYYY-MM-DD> `
  --output data\evaluation-results\live-run
```

Only pass rates verified against the provider's current billing page. Record the URL, applicable tier, and verification date so a reviewer can audit the calculation. Without rates, the report records `cost.status=not_calculated` instead of inventing a monetary value.

## Retained evidence

Each scenario directory in a generated run contains:

- `scenario-input.json`: fixed task definition and evidence boundaries;
- `baseline-preflight.json`: public and hidden baseline scores plus raw command results;
- `frozen-spec.json`: revision, file authorization, commands, budgets, hashes, and validation policy;
- `trial-ledger.json`: Keep/Reject decisions and command results when a ledger is available;
- `validation-report.json`: fresh hidden validation and integrity checks when validation is reached;
- `initial-candidate.py` and `final-candidate.py`: exact before/after source;
- `result.json`: normalized outcome, model usage, cost basis, failures, hashes, and artifact links.

The run root contains `suite-summary.json` for machines and `README.md` for reviewers. Release evidence should come from a clean committed revision; live mode refuses a dirty source tree unless `--allow-dirty` is explicitly supplied for a non-release experiment.
