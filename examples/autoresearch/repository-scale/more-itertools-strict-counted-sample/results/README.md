# Retained more-itertools live runs

| Harness revision | Outcome | Public | Hidden | Attempts | Usage reports | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| [`da3cfdd-live`](da3cfdd-live/) | `candidate_stopped` | `4/6 -> 4/6` | `1/6 -> 1/6` | 3 | 0 | not calculated | [`provider_requests_failed_no_candidate`](da3cfdd-live/review.json) |

All three bounded provider attempts failed before returning model content or token usage: one `RemoteProtocolError` and two `ReadTimeout` failures. No candidate patch was produced, no trial was accepted, and fresh hidden validation remained at the frozen baseline.

This run is retained as provider/request-boundary evidence. It is not classified as a model-generated repair failure because the provider returned no candidate to evaluate, and the absence of usage data is not presented as zero cost.

Candidate source and patch artifacts preserve the exact bytes retained by the runner. `.gitattributes` prevents line-ending normalization and limits the whitespace exemption to those evidence file types.
