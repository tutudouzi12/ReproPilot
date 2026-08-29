from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load_module("fasttext_reproduction_host", ROOT / "run.py")
container = load_module("fasttext_reproduction_container", ROOT / "container_runner.py")


def test_experiment_freezes_public_inputs_and_metric_boundary():
    experiment = host.load_experiment(ROOT / "experiment.json")
    assert experiment["repository"]["revision"] == "206179d64c1730862328e9b750e98bd8aa1c16b5"
    assert experiment["repository"]["license"] == "BSD-3-Clause"
    assert experiment["repository"]["additional_patent_grant"] == "PATENTS"
    assert experiment["dataset"]["archive_sha256"] == "9a8c300eabb45750237fcc669f61cb8a3448f3ef6f6098e1ce340e444f6872be"
    assert experiment["paper"]["reported"] == {
        "baseline_accuracy_percent": 91.5,
        "bigram_accuracy_percent": 92.5,
        "bigram_gain_percentage_points": 1.0,
    }
    assert experiment["claim"]["minimum_bigram_gain_percentage_points"] == 0.5


def test_normalization_matches_official_shell_pipeline_examples():
    raw = '3,"Wall St.","Company\'s profit: up!"'
    assert container.normalize_line(raw) == (
        "__label__3 , wall st . , company ' s profit up !"
    )


def test_fasttext_test_output_is_parsed_as_percent():
    count, accuracy = container.parse_test_output("N\t7600\nP@1\t0.925\nR@1\t0.925\n")
    assert count == 7600
    assert accuracy == 92.5
    historical_count, historical_accuracy = container.parse_test_output(
        "P@1: 0.925\nNumber of examples: 7600\n"
    )
    assert historical_count == 7600
    assert historical_accuracy == 92.5


def test_summary_keeps_runs_separate_and_computes_gain():
    trials = [
        {"variant": "unigram", "accuracy_percent": 91.4, "training_seconds": 1.0},
        {"variant": "bigram", "accuracy_percent": 92.4, "training_seconds": 2.0},
        {"variant": "unigram", "accuracy_percent": 91.6, "training_seconds": 1.2},
        {"variant": "bigram", "accuracy_percent": 92.6, "training_seconds": 2.2},
    ]
    summary = container.summarize(trials)
    assert summary["unigram"]["mean_accuracy_percent"] == 91.5
    assert summary["bigram"]["mean_accuracy_percent"] == 92.5
    assert summary["bigram_gain_percentage_points"] == 1.0


def test_deterministic_adjudication_has_hard_contradiction_boundary():
    assert host.criterion_status_absolute(92.0, 92.5, 1.0) == "verified"
    assert host.criterion_status_absolute(90.8, 92.5, 1.0) == "partially_reproduced"
    assert host.criterion_status_absolute(89.0, 92.5, 1.0) == "contradicted"
    assert host.criterion_status_gain(0.6, 0.5) == "verified"
    assert host.criterion_status_gain(0.2, 0.5) == "partially_reproduced"
    assert host.criterion_status_gain(-0.1, 0.5) == "contradicted"


def test_adjudication_uses_product_claim_evidence_contract():
    experiment = host.load_experiment(ROOT / "experiment.json")
    metrics = {
        "summary": {
            "unigram": {"runs": 3, "mean_accuracy_percent": 91.5},
            "bigram": {"runs": 3, "mean_accuracy_percent": 92.5},
            "bigram_gain_percentage_points": 1.0,
        }
    }
    provenance = {"container": {"network": "none"}}
    rubric, comparison, graph = host.adjudicate(experiment, metrics, provenance)
    assert rubric["sha256"]
    assert comparison["criteria"]["absolute_accuracy"]["status"] == "verified"
    assert graph["claims"][0]["status"] == "verified"
    assert graph["summary"]["criterion_evidence_coverage"] == 1.0
    json.dumps(graph)


def test_retained_docker_evidence_is_hash_linked_and_path_sanitized():
    result_dir = ROOT / "results" / "2026-08-29-docker"
    for artifact in result_dir.iterdir():
        if artifact.is_file():
            assert b"\r\n" not in artifact.read_bytes(), f"evidence must use LF: {artifact.name}"
    bundle = json.loads((result_dir / "evidence-bundle.json").read_text(encoding="utf-8"))
    assert bundle["verdict"] == "verified"
    for name, metadata in bundle["files"].items():
        artifact = result_dir / name
        assert artifact.stat().st_size == metadata["bytes"]
        assert host.sha256_file(artifact) == metadata["sha256"]

    metrics = json.loads((result_dir / "run-metrics.json").read_text(encoding="utf-8"))
    assert metrics["source_revision"] == "206179d64c1730862328e9b750e98bd8aa1c16b5"
    assert metrics["summary"]["bigram"]["mean_accuracy_percent"] == 92.433333
    assert metrics["summary"]["bigram_gain_percentage_points"] == 1.133333

    provenance_text = (result_dir / "provenance.json").read_text(encoding="utf-8")
    assert "<DATASET_ARCHIVE>" in provenance_text
    assert "ReproPilot-paper-case" not in provenance_text
