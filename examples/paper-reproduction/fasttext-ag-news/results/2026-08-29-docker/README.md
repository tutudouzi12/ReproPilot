# fastText AG News bounded reproduction

## Verdict

**verified** - On AG News, adding word bigrams to the h=10 fastText classifier improves test accuracy from 91.5% to 92.5%.

This result covers one frozen claim from Table 1 and Section 3.1 of *Bag of Tricks for Efficient Text Classification*. It is not a reproduction of every dataset, timing result, or conclusion in the paper.

## Observed results

| Shuffle seed | Unigram accuracy | Bigram accuracy | Gain |
|---:|---:|---:|---:|
| 1729 | 91.300% | 92.500% | 1.200 pp |
| 2718 | 91.200% | 92.200% | 1.000 pp |
| 3141 | 91.400% | 92.600% | 1.200 pp |

- Mean unigram accuracy: `91.300%`
- Mean bigram accuracy: `92.433%`
- Mean bigram gain: `1.133` percentage points
- Paper values: `91.5%` unigram and `92.5%` bigram
- Frozen absolute tolerance: `+/-1.0` percentage points
- Frozen minimum gain: `0.5` percentage points

## Frozen inputs

- Paper: arXiv `1607.01759`, PDF SHA-256 `6cbcf620c2537ed54dfb9ed0d843a83689b82dc41dcd305bfb2e82425d4d7906`
- Source: `https://github.com/facebookresearch/fastText.git` at `206179d64c1730862328e9b750e98bd8aa1c16b5`
- Source archive SHA-256: `24f30b4c939148f60174ea8d9995b22b9f1752dd2cfa16ed34e8d89c02c02b7d`
- Dataset archive SHA-256: `9a8c300eabb45750237fcc669f61cb8a3448f3ef6f6098e1ce340e444f6872be`
- Base image: `debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241`
- Experiment network: `none`

## Evidence

- `experiment-spec.json`: frozen claim, source, data, environment, metric, and tolerance
- `run-metrics.json`: all per-seed measurements and summaries
- `comparison-report.json`: deterministic paper-to-run comparison
- `claim-rubric.json`: criteria frozen before adjudication
- `claim-evidence-graph.json`: criterion-level verdicts and artifact hashes
- `provenance.json`: source, data, image, execution boundary, and timestamps
- `evidence-bundle.json`: hash-indexed manifest of the evidence files

## Boundaries

- The official script uses an unseeded Perl shuffle; this reproduction fixes three shuffle seeds so data order can be replayed.
- The official fastText commit is pinned to the paper's 2016-08-09 submission date, but it is compiled on Debian bookworm rather than the authors' original host environment.
- Runtime is retained as environment evidence but is not compared with the paper's hardware-dependent one-second timing claim.
- Accuracy agreement under this protocol does not establish exact equivalence to the authors' 2016 hardware, compiler, or asynchronous thread schedule.
- The dataset is downloaded at run time and is not redistributed by ReproPilot.
