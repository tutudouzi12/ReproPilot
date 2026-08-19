from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import LLMClient, RoutedAgentExecutor
from app.autoresearch import (
    CandidatePatch,
    CandidateProposal,
    CommandResult,
    TrialLedger,
    aggregate_scores,
    freeze_research_spec,
    parse_metric,
    proposal_context,
    run_autoresearch,
    validate_autoresearch,
)
from app.models import PlanGraph, TaskNode


REVISION = "a" * 40


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "candidate.py").write_text("SCORE = 1\n", encoding="utf-8")
    (tmp_path / "evaluator.py").write_text("# public evaluator\n", encoding="utf-8")
    (tmp_path / "holdout.py").write_text("# hidden evaluator\n", encoding="utf-8")
    return tmp_path


def payload(**overrides):
    value = {
        "version": "autoresearch.spec/v1",
        "name": "bounded-test",
        "objective": "Improve a deterministic score",
        "repository_revision": REVISION,
        "editable_files": ["candidate.py"],
        "protected_files": ["evaluator.py", "holdout.py"],
        "eval_command": ["python", "evaluator.py"],
        "holdout_command": ["python", "holdout.py"],
        "metric_key": "metrics.score",
        "direction": "maximize",
        "min_delta": 0.1,
        "holdout_min_delta": 0.1,
        "max_trials": 3,
        "search_runs": 3,
        "search_aggregation": "worst",
        "validation_runs": 3,
    }
    value.update(overrides)
    return value


def freeze(root: Path, **overrides):
    return freeze_research_spec(
        root,
        payload(**overrides),
        {"requested_revision": REVISION, "repository_commit": REVISION},
        source_path="autoresearch.json",
    )


def score_from(root: Path) -> float:
    return float(root.joinpath("candidate.py").read_text(encoding="utf-8").split("=")[1])


def evaluator_for(root: Path, *, mutate_protected: bool = False):
    async def evaluate(command: list[str]) -> CommandResult:
        score = score_from(root)
        if command[-1] == "holdout.py":
            score -= 0.25
        if mutate_protected and score > 1:
            root.joinpath("evaluator.py").write_text("tampered\n", encoding="utf-8")
        return CommandResult(command=command, exit_code=0, stdout=json.dumps({"metrics": {"score": score}}))

    return evaluate


def test_freeze_rejects_revision_drift_and_evaluator_overlap(tmp_path):
    root = workspace(tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        freeze_research_spec(root, payload(), {"requested_revision": REVISION, "repository_commit": "b" * 40})
    with pytest.raises(ValueError, match="overlap"):
        freeze(root, editable_files=["candidate.py", "evaluator.py"])
    with pytest.raises(ValueError, match="package specifier"):
        freeze(root, dependencies=["safe-package", "--index-url=https://evil.invalid"])


def test_metric_parser_uses_last_nested_json_and_robust_aggregation():
    stdout = 'progress {"metrics":{"score":1.0}}\nfinal {"metrics":{"score":2.5}}\n'
    assert parse_metric(stdout, "metrics.score") == 2.5
    assert aggregate_scores([1.0, 3.0, 2.0], "mean", "maximize") == 2.0
    assert aggregate_scores([1.0, 3.0, 2.0], "median", "maximize") == 2.0
    assert aggregate_scores([1.0, 3.0, 2.0], "worst", "maximize") == 1.0
    assert aggregate_scores([1.0, 3.0, 2.0], "worst", "minimize") == 3.0


@pytest.mark.asyncio
async def test_llm_client_parses_openai_compatible_usage(monkeypatch):
    def handler(request):
        assert request.url.path == "/compatible-mode/v1/chat/completions"
        return __import__("httpx").Response(
            200,
            json={
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
            },
        )

    httpx = __import__("httpx")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example/compatible-mode/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-coder")
    completion = await LLMClient(transport=httpx.MockTransport(handler)).complete_with_usage("system", "user")

    assert completion.content == "OK"
    assert completion.usage.model_dump() == {
        "provider": "dashscope.example",
        "model": "test-coder",
        "request_count": 1,
        "reported_request_count": 1,
        "prompt_tokens": 11,
        "completion_tokens": 2,
        "total_tokens": 13,
    }


@pytest.mark.asyncio
async def test_autoresearch_dependencies_only_use_frozen_contract(tmp_path):
    root = workspace(tmp_path)
    (root / "unrelated.py").write_text("import httpx\n", encoding="utf-8")
    spec = freeze(root, dependencies=[])
    task = TaskNode(
        name="Resolve frozen dependencies",
        type="resolve_dependencies",
        description="Resolve only the AutoResearch contract",
        assigned_to="coder_agent",
        inputs={
            "workspace_path": str(root),
            "generated_code": "import httpx\n",
            "research_spec": spec.model_dump_json(),
        },
    )
    plan = PlanGraph(user_intent="test", intent_type="AutoResearch", nodes=[task], edges=[])

    result = await RoutedAgentExecutor().execute(task, plan)

    assert result.status == "completed"
    assert json.loads(result.structured_data) == {
        "packages": [],
        "python": "3.11",
        "source": "frozen_autoresearch_contract",
    }


@pytest.mark.asyncio
async def test_run_keeps_improvement_rolls_back_regression_and_hides_holdout(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root)
    contexts = []
    proposals = iter([
        CandidateProposal(hypothesis="increase score", patches=[CandidatePatch(path="candidate.py", content="SCORE = 2\n")]),
        CandidateProposal(hypothesis="bad regression", patches=[CandidatePatch(path="candidate.py", content="SCORE = 0\n")]),
        CandidateProposal(status="stop", reason="done"),
    ])

    async def propose(context):
        contexts.append(context)
        return next(proposals)

    ledger = await run_autoresearch(root, spec, evaluator_for(root), propose)
    assert ledger.status == "completed"
    assert ledger.baseline_score == 1.0
    assert ledger.best_score == 2.0
    assert ledger.accepted_trials == 1
    assert [trial.status for trial in ledger.trials] == ["baseline", "kept", "rejected", "stopped"]
    assert root.joinpath("candidate.py").read_text(encoding="utf-8") == "SCORE = 2\n"
    assert "holdout_command" not in contexts[0]["spec"]
    assert all("holdout.py" not in json.dumps(context, ensure_ascii=False) for context in contexts)
    assert contexts[0]["rejected_feedback"] == ""
    assert '"score": 2.0' in contexts[1]["rejected_feedback"]
    assert "trial budget allows further improvement" in contexts[1]["rejected_feedback"]
    assert '"score": 0.0' in contexts[2]["rejected_feedback"]

    report = await validate_autoresearch(root, spec, ledger, evaluator_for(root))
    assert report.status == "passed"
    assert report.validation_mode == "hidden_holdout"
    assert report.observed_scores == [1.75, 1.75, 1.75]


@pytest.mark.asyncio
async def test_run_restores_workspace_after_protected_mutation(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root, max_trials=1, search_runs=1)

    async def propose(_context):
        return CandidateProposal(patches=[CandidatePatch(path="candidate.py", content="SCORE = 2\n")])

    with pytest.raises(RuntimeError, match="changed"):
        await run_autoresearch(root, spec, evaluator_for(root, mutate_protected=True), propose)
    assert root.joinpath("candidate.py").read_text(encoding="utf-8") == "SCORE = 1\n"
    assert root.joinpath("evaluator.py").read_text(encoding="utf-8") == "# public evaluator\n"


@pytest.mark.asyncio
async def test_run_retains_exception_type_when_proposer_message_is_empty(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root, max_trials=1, search_runs=1)

    async def propose(_context):
        raise TimeoutError()

    ledger = await run_autoresearch(root, spec, evaluator_for(root), propose)

    assert ledger.trials[-1].status == "rejected"
    assert ledger.trials[-1].reason == "TimeoutError"


@pytest.mark.asyncio
async def test_validation_rejects_candidate_hash_drift(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root, max_trials=1, search_runs=1)
    ledger = TrialLedger(
        spec_sha256=spec.spec_sha256,
        metric_key=spec.metric_key,
        direction=spec.direction,
        baseline_score=1,
        best_score=2,
        holdout_baseline_score=0.75,
        max_trials=1,
        best_candidate_files={"candidate.py": "0" * 64},
    )
    report = await validate_autoresearch(root, spec, ledger, evaluator_for(root))
    assert report.status == "failed"
    assert report.candidate_intact is False
    assert "trial ledger" in report.reason


@pytest.mark.asyncio
async def test_validation_rejects_ledger_from_another_spec(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root)
    ledger = TrialLedger(spec_sha256="0" * 64, metric_key=spec.metric_key, direction=spec.direction, max_trials=1)
    with pytest.raises(ValueError, match="does not match"):
        await validate_autoresearch(root, spec, ledger, evaluator_for(root))


def test_proposal_context_excludes_hidden_contract(tmp_path):
    root = workspace(tmp_path)
    spec = freeze(root)
    ledger = TrialLedger(spec_sha256=spec.spec_sha256, metric_key=spec.metric_key, direction=spec.direction, max_trials=3)
    encoded = json.dumps(proposal_context(root, spec, ledger), ensure_ascii=False)
    assert "holdout_command" not in encoded
    assert "holdout.py" not in encoded
