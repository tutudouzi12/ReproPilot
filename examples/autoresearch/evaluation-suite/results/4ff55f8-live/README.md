# ReproPilot evaluation scenario run

- Recorded at: `2026-08-14T08:14:10.223488Z`
- Repository revision: `4ff55f8b1dea077e054c05ec966f843a866e344b`
- Source tree dirty before run: `false`
- Requested mode: `live`
- Result: `failed`

| Scenario | Proposer | Baseline | Best | Observed outcome | Expected | Requests | Tokens | Cost |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `evaluator-timeout-rejected` | scripted_fault_injection | 1.0 | 1.0 | candidate_rejected_timeout | candidate_rejected_timeout | 0 | 0 | 0.0 CNY |
| `hidden-holdout-failed` | scripted_fault_injection | 0.6666666666666666 | 1.0 | hidden_validation_failed | hidden_validation_failed | 0 | 0 | 0.0 CNY |
| `identifier-normalization-success` | live_model | 0.6666666666666666 | 0.6666666666666666 | candidate_rejected | validation_passed | 1 | 865 | 0.00526 CNY |
| `protected-mutation-aborts` | scripted_fault_injection | 0.5 | None | integrity_abort | integrity_abort | 0 | 0 | 0.0 CNY |
| `syntax-guard-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_guard | candidate_rejected_guard | 0 | 0 | 0.0 CNY |
| `unauthorized-patch-rejected` | scripted_fault_injection | 0.5 | 0.5 | candidate_rejected_contract | candidate_rejected_contract | 0 | 0 | 0.0 CNY |
| `zero-boundary-success` | live_model | 0.6666666666666666 | 1.0 | validation_passed | validation_passed | 2 | 2069 | 0.012776 CNY |

Scripted fault-injection scenarios validate deterministic governance and failure handling; they are not model-quality claims. Live-model scenarios record provider-reported token usage and calculate monetary cost only when explicit rates are supplied.

## Live-run interpretation

- `zero-boundary-success` reached `1.0` on the public evaluator and passed all three hidden validation runs at `1.0`.
- `identifier-normalization-success` did not improve over its `0.6667` public baseline. Its first proposal used the out-of-contract status `proposed` and was rejected before applying a patch.
- The second identifier-normalization trial retained an empty rejection reason and no provider-reported usage. This run therefore cannot prove whether that attempt reached the provider; the missing exception type is an observability boundary, not evidence of a model response.
- The suite result is intentionally `failed` because one live-model scenario did not match its expected outcome. No result was rewritten to make the run pass.

## Cost provenance

- Provider/model: DashScope OpenAI-compatible endpoint, `qwen3-coder-plus`.
- Official price page: <https://help.aliyun.com/zh/model-studio/model-pricing>
- Rate verified on 2026-08-14 for the Mainland China `0 < Tokens <= 32K` tier: input `4 CNY / 1M tokens`, output `16 CNY / 1M tokens`.
- The recorded cost is derived from provider-reported tokens and these public list rates. It is not a billing-console receipt and does not include discounts or free quota.
