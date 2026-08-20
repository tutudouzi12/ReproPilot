# Retained adversarial follow-up runs

| Harness revision | Outcome | Public | Hidden | Attempts | Tokens | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| [`d7ad05b-live`](d7ad05b-live/) | `hidden_validation_failed` | `4/6 -> 6/6` | `2/10 -> 9/10` | 1 | 10,846 | 0.058516 CNY | [`hidden_holdout_rejected_eager_iterable_materialization`](d7ad05b-live/review.json) |

The candidate passed the public evaluator and the complete upstream suite, so its trial was retained as the best public candidate. Fresh hidden validation then failed all three repetitions on `strict_counts_remain_lazy`. The patch eagerly converts both `population` and `counts` to lists, changing the streaming behavior for unknown-length iterables. This is a hidden-acceptance failure, not a provider failure or syntax rejection.

This candidate-informed follow-up reuses the same pinned more-itertools repository and must not be counted as an independent repository sample. Its purpose is to preserve the progression from an automated pass, through manual rejection, to a versioned hidden contract that detects the observed regression automatically.
