# Retained Humanize live runs

| Harness revision | Outcome | Public | Hidden | Requests | Tokens | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [`6511078-live`](6511078-live/) | `validation_passed` | `4/6 -> 6/6` | `1/6 -> 6/6` | 1 | 3,387 | 0.033132 CNY | [`contract_pass_with_review_boundary`](6511078-live/review.json) |

The live model repaired the frozen contract in one request, and the candidate passed the pinned upstream suite (`701 passed, 69 skipped`) on each of three public-search runs. Three fresh hidden runs also passed `6/6` with zero score variance.

The automated result is retained as a successful contract repair, not as an upstream-readiness claim. Manual review found the candidate behavior matched the historical maintainer fix across an additional 144-case decimal, binary, GNU, sign, precision, rollover, and maximum-suffix matrix, but the model used substantially more branching than the concise six-line upstream fix. The review therefore preserves the pass while recording maintainability as a boundary.

Candidate source and patch artifacts preserve the exact upstream and model-produced bytes, including trailing whitespace. `.gitattributes` prevents line-ending normalization and limits the whitespace exemption to those evidence file types.
