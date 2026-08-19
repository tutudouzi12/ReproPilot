# Retained Rank-BM25 live runs

| Harness revision | Outcome | Public | Hidden | Requests | Tokens | Token-derived cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| [`af1178b-live`](af1178b-live/) | `hidden_validation_failed` | `5/9 -> 8/9` | `1/4 -> 3/4` | 3 | 26,224 | 0.225568 CNY |
| [`66b1b7a-live`](66b1b7a-live/) | `validation_passed` | `5/9 -> 9/9` | `1/4 -> 4/4` | 1 | 7,176 | 0.0717 CNY |

The first live run is intentionally retained as failure evidence. Its first candidate improved and was kept, but the search exhausted its request cap without resolving the all-empty-document case; all three fresh hidden runs remained at `3/4`.

The second live run passed the frozen automated contract in one request. Its [`review.json`](66b1b7a-live/review.json) separately records a combined-input check-order caveat, so the contract pass is not presented as an upstream-readiness claim. Both runs retain their exact harness revisions; the active task later replaced Windows working-tree byte hashes with portable Git-blob hashes.

Candidate source and patch artifacts preserve the exact upstream and model-produced bytes, including existing trailing whitespace; `.gitattributes` prevents line-ending normalization and limits the whitespace exemption to those evidence file types.
