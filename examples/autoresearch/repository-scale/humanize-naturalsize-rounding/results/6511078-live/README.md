# Humanize naturalsize rounding rollover live repository evaluation

- Recorded at: `2026-08-19T09:09:41.041149Z`
- Harness revision: `651107835e1d0bab8d7bc5eacbcd5f480a515753`
- Target revision: `976484a655df046aa6849f440a4f0cd44fc4918c`
- Outcome: `validation_passed`
- Public baseline -> best: `0.6666666666666666` -> `1.0`
- Hidden baseline -> observed: `0.16666666666666666` -> `1.0`
- Model: `dashscope.aliyuncs.com/qwen3-coder-plus`
- Requests/tokens: `1` / `3387`
- Token-derived cost: `0.033132 CNY`
- Editable files: `src/humanize/filesize.py`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.66666667 | frozen baseline |
| 1 | kept | keep | 1 | metrics.rounding_score improved from 0.66666667 to 1 |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
