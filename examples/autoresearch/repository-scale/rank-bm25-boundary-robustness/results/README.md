# Retained Rank-BM25 live runs

| Harness revision | Outcome | Public | Hidden | Requests | Tokens | Token-derived cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| [`af1178b-live`](af1178b-live/) | `hidden_validation_failed` | `5/9 -> 8/9` | `1/4 -> 3/4` | 3 | 26,224 | 0.225568 CNY |

The first live run is intentionally retained as failure evidence. Its first candidate improved and was kept, but the search exhausted its request cap without resolving the all-empty-document case; all three fresh hidden runs remained at `3/4`.

Candidate source and patch artifacts preserve the exact upstream and model-produced bytes, including existing trailing whitespace; `.gitattributes` prevents line-ending normalization and limits the whitespace exemption to those evidence file types.
