# Repository-scale AutoResearch tasks

This directory contains bounded tasks against real, independently versioned GitHub repositories. A task is release evidence only when the repository URL, full commit SHA, selected Git-blob hashes, dependency versions, original test command, public evaluator, hidden evaluator, and observed baseline are all retained.

The local `.gitattributes` disables checkout line-ending rewriting for frozen inputs and retained artifacts so their recorded SHA256 values remain stable across Git configurations.

These tasks exercise repository acquisition and real project code. They remain module-level repair experiments rather than claims about the full upstream product or a general software-engineering benchmark.

## Pilot tasks

| Task | Provenance | Frozen repository | Baseline | Scope |
| --- | --- | --- | ---: | --- |
| [`rank-bm25-boundary-robustness`](rank-bm25-boundary-robustness/) | ReproPilot boundary contract | `dorianbrown/rank_bm25@47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099` | public `5/9`, hidden `1/4` | One real module plus the upstream test suite |
| [`humanize-naturalsize-rounding`](humanize-naturalsize-rounding/) | Historical merged PR [#329](https://github.com/python-humanize/humanize/pull/329) | `python-humanize/humanize@976484a655df046aa6849f440a4f0cd44fc4918c` | public `4/6`, hidden `1/6` | One historical defect plus 701 upstream tests |
| [`more-itertools-strict-counted-sample`](more-itertools-strict-counted-sample/) | Historical merged PR [#944](https://github.com/more-itertools/more-itertools/pull/944) | `more-itertools/more-itertools@18225d856665bfc3bfdfcdbfa585290f92645daf` | public `4/6`, hidden `1/6` | Counted-sampling exception flow plus 825 upstream tests |
| [`more-itertools-strict-counted-sample-adversarial`](more-itertools-strict-counted-sample-adversarial/) | Candidate-informed follow-up | Same pinned `more-itertools` base | public `4/6`, hidden `2/10` | Lazy-iterator non-regression; excluded from independent repository counts |

The pilot therefore contains four tasks across three unique repositories. The adversarial follow-up is retained to show how manual review hardened a missed boundary; it is not an independent repository sample and must remain separately labeled in aggregates.

## Baseline contract

`scripts/run_repository_baseline.py` refuses to score a checkout when its GitHub origin, HEAD commit, cleanliness, selected Git-blob hashes, or filtered working-tree contents differ from `task.json`. Git-blob hashing keeps the frozen identity stable across checkout line-ending policies. The runner executes the upstream tests before the project-defined public and hidden evaluators and retains portable command forms, working-directory roles, stdout, stderr, duration, Python environment, dependency versions, scores, and evidence boundaries.

The baseline runner does not call an LLM and does not claim that a repair has been produced. Candidate search and retained Keep/Reject evidence belong in a later commit after this frozen starting point is reviewable.

## Bounded live search

After the baseline task is committed, `scripts/run_repository_evaluation.py` materializes the pinned checkout in a temporary workspace, freezes the AutoResearch contract, caps provider requests, and retains the exact model responses, candidate patch, Keep/Reject ledger, hidden validation, provider token usage, and cost basis. Release evidence requires a clean harness checkout and never overwrites an existing result directory.

Use `--preflight-only` first to validate the frozen checkout and evaluator without making a provider request. Live evaluator subprocesses receive a stripped environment; they are local processes rather than a network-isolated sandbox, and the result states that boundary explicitly.

Retained live evidence is indexed under each task's `results/` directory. Follow-up model requests receive deduplicated public evaluator stdout and stderr after partial improvements or rejections; hidden evaluator commands and content remain excluded from proposer context.

## Batch preflight

[`benchmark.json`](benchmark.json) freezes task membership, provenance, aggregate metric names, and the SHA-256 values of each retained contract artifact. Prepare every pinned checkout and fixed Python environment as described by its task README, then validate all tasks without making a model request:

```powershell
py -3.11 scripts\run_repository_benchmark_preflight.py `
  --benchmark examples\autoresearch\repository-scale\benchmark.json `
  --checkout rank-bm25-boundary-robustness=<rank-checkout> `
  --python rank-bm25-boundary-robustness=<rank-python> `
  --checkout humanize-naturalsize-rounding=<humanize-checkout> `
  --python humanize-naturalsize-rounding=<humanize-python> `
  --checkout more-itertools-strict-counted-sample=<more-itertools-checkout> `
  --python more-itertools-strict-counted-sample=<more-itertools-python> `
  --checkout more-itertools-strict-counted-sample-adversarial=<more-itertools-checkout> `
  --python more-itertools-strict-counted-sample-adversarial=<more-itertools-python> `
  --output <preflight-report.json>
```

The runner checks benchmark-to-task identity and contract hashes before delegating to the repository preflight. It continues across task failures, emits one aggregate result, and exits non-zero if any selected task fails. Retained output replaces local checkout and interpreter paths with task-scoped placeholders.
