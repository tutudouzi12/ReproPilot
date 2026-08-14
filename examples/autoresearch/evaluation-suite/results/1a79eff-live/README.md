# ReproPilot evaluation scenario run

- Recorded at: `2026-08-14T08:28:59.755011Z`
- Repository revision: `1a79eff1d84d30be1e600b672defba18c2f39e3d`
- Source tree dirty before run: `false`
- Requested mode: `live`
- Result: `passed`

| Scenario | Proposer | Baseline | Best | Observed outcome | Expected | Requests | Tokens | Cost |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `evaluator-timeout-rejected` | scripted_fault_injection | 1.0 | 1.0 | candidate_rejected_timeout | candidate_rejected_timeout | 0 | 0 | 0.0 CNY |
| `hidden-holdout-failed` | scripted_fault_injection | 0.6666666666666666 | 1.0 | hidden_validation_failed | hidden_validation_failed | 0 | 0 | 0.0 CNY |
| `identifier-normalization-success` | live_model | 0.6666666666666666 | 1.0 | validation_passed | validation_passed | 1 | 884 | 0.005204 CNY |
| `protected-mutation-aborts` | scripted_fault_injection | 0.5 | None | integrity_abort | integrity_abort | 0 | 0 | 0.0 CNY |
| `syntax-guard-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_guard | candidate_rejected_guard | 0 | 0 | 0.0 CNY |
| `unauthorized-patch-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_contract | candidate_rejected_contract | 0 | 0 | 0.0 CNY |
| `zero-boundary-success` | live_model | 0.6666666666666666 | 1.0 | validation_passed | validation_passed | 1 | 939 | 0.005964 CNY |

Scripted fault-injection scenarios validate deterministic governance and failure handling; they are not model-quality claims. Live-model scenarios record provider-reported token usage and calculate monetary cost only when explicit rates are supplied.

## Cost provenance

- Pricing source: <https://help.aliyun.com/zh/model-studio/model-pricing>
- Pricing tier: Mainland China, 0<Tokens<=32K
- Rate verified at: 2026-08-14
- Cost is derived from provider-reported tokens and the supplied public list rates; it is not a billing-console receipt.
