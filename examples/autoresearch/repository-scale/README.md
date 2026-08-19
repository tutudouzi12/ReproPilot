# Repository-scale AutoResearch tasks

This directory contains bounded tasks against real, independently versioned GitHub repositories. A task is release evidence only when the repository URL, full commit SHA, selected source-file hashes, dependency versions, original test command, public evaluator, hidden evaluator, and observed baseline are all retained.

These tasks exercise repository acquisition and real project code. They remain module-level repair experiments rather than claims about the full upstream product or a general software-engineering benchmark.

## First task

| Task | Frozen repository | Baseline | Scope |
| --- | --- | ---: | --- |
| [`rank-bm25-boundary-robustness`](rank-bm25-boundary-robustness/) | `dorianbrown/rank_bm25@47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099` | public `5/9`, hidden `1/4` | One real module plus the upstream test suite |

## Baseline contract

`scripts/run_repository_baseline.py` refuses to score a checkout when its GitHub origin, HEAD commit, cleanliness, or selected source hashes differ from `task.json`. It runs the upstream tests before the project-defined public and hidden evaluators and retains portable command forms, working-directory roles, stdout, stderr, duration, Python environment, dependency versions, scores, and evidence boundaries.

The baseline runner does not call an LLM and does not claim that a repair has been produced. Candidate search and retained Keep/Reject evidence belong in a later commit after this frozen starting point is reviewable.

## Bounded live search

After the baseline task is committed, `scripts/run_repository_evaluation.py` materializes the pinned checkout in a temporary workspace, freezes the AutoResearch contract, caps provider requests, and retains the exact model responses, candidate patch, Keep/Reject ledger, hidden validation, provider token usage, and cost basis. Release evidence requires a clean harness checkout and never overwrites an existing result directory.

Use `--preflight-only` first to validate the frozen checkout and evaluator without making a provider request. Live evaluator subprocesses receive a stripped environment; they are local processes rather than a network-isolated sandbox, and the result states that boundary explicitly.

Retained live evidence is indexed under each task's `results/` directory. Follow-up model requests receive deduplicated public evaluator stdout and stderr after partial improvements or rejections; hidden evaluator commands and content remain excluded from proposer context.
