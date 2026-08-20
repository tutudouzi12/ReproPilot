# Retained Flask IPv6 runs

| Harness revision | Automated outcome | Public | Hidden | Attempts | Tokens | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [`7ec8f6e-live`](7ec8f6e-live/) | `validation_passed` | `2/4 -> 4/4` | `2/5 -> 5/5` | 3 | 35,392 | 0.169744 CNY | [`reject`](7ec8f6e-live/review.json) |

The automated pass is retained together with the complete three-request trajectory: one non-improving patch, one patch-application rejection, and one kept candidate. Manual review rejects the final candidate because malformed brackets and out-of-range ports bypass validation, and the retained patch fails the pinned Flask Ruff configuration. The run therefore contributes real automated-pass and manual-rejection evidence, not a manually accepted repair claim.
