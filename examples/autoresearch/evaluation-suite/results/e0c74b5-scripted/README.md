# ReproPilot evaluation scenario run

- Recorded at: `2026-08-14T08:02:05.322081Z`
- Repository revision: `e0c74b53846d02ba0499c85af90655e2a634ba2b`
- Source tree dirty before run: `false`
- Requested mode: `scripted`
- Result: `passed`

| Scenario | Proposer | Baseline | Best | Observed outcome | Expected | Requests | Tokens | Cost |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `evaluator-timeout-rejected` | scripted_fault_injection | 1.0 | 1.0 | candidate_rejected_timeout | candidate_rejected_timeout | 0 | 0 | 0.0 USD |
| `hidden-holdout-failed` | scripted_fault_injection | 0.6666666666666666 | 1.0 | hidden_validation_failed | hidden_validation_failed | 0 | 0 | 0.0 USD |
| `identifier-normalization-success` | scripted_fault_injection | 0.6666666666666666 | 1.0 | validation_passed | validation_passed | 0 | 0 | 0.0 USD |
| `protected-mutation-aborts` | scripted_fault_injection | 0.5 | None | integrity_abort | integrity_abort | 0 | 0 | 0.0 USD |
| `syntax-guard-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_guard | candidate_rejected_guard | 0 | 0 | 0.0 USD |
| `unauthorized-patch-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_contract | candidate_rejected_contract | 0 | 0 | 0.0 USD |
| `zero-boundary-success` | scripted_fault_injection | 0.6666666666666666 | 1.0 | validation_passed | validation_passed | 0 | 0 | 0.0 USD |

Scripted fault-injection scenarios validate deterministic governance and failure handling; they are not model-quality claims. Live-model scenarios record provider-reported token usage and calculate monetary cost only when explicit rates are supplied.
