#!/usr/bin/env python3
"""Build, run, and adjudicate the bounded fastText AG News reproduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXAMPLE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = EXAMPLE_DIR.parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.claim_evidence import (  # noqa: E402
    ClaimCriterion,
    ClaimRubric,
    PaperClaim,
    build_evidence_graph,
    normalize_rubric,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    text: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=text,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as exc:
        if not capture_output:
            raise
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        raise RuntimeError(
            f"command failed with exit code {exc.returncode}; "
            f"stdout={' '.join(stdout.split())[:1000]!r}; "
            f"stderr={' '.join(stderr.split())[:1000]!r}"
        ) from exc


def load_experiment(path: Path) -> dict[str, Any]:
    experiment = json.loads(path.read_text(encoding="utf-8"))
    if experiment.get("version") != "repropilot.paper-reproduction/v1":
        raise ValueError("unsupported paper reproduction specification")
    seeds = experiment.get("protocol", {}).get("shuffle_seeds", [])
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("shuffle seeds must be non-empty and unique")
    return experiment


def require_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected.lower():
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")


def ensure_dataset(
    experiment: dict[str, Any], cache_dir: Path, supplied_archive: Path | None
) -> Path:
    dataset = experiment["dataset"]
    expected_hash = dataset["archive_sha256"]
    if supplied_archive is not None:
        path = supplied_archive.resolve()
        require_hash(path, expected_hash, "dataset archive")
        return path
    target = cache_dir / "ag_news_csv.tgz"
    if target.exists() and sha256_file(target) == expected_hash:
        return target.resolve()
    partial = target.with_suffix(".tgz.partial")
    partial.unlink(missing_ok=True)
    print(f"Downloading frozen dataset: {dataset['url']}", flush=True)
    urllib.request.urlretrieve(dataset["url"], partial)
    require_hash(partial, expected_hash, "downloaded dataset archive")
    partial.replace(target)
    return target.resolve()


def git_command(source: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return run_command(["git", "-C", str(source), *args], text=text)


def source_archive_sha256(source: Path) -> str:
    archive = git_command(source, "archive", "--format=tar", "HEAD", text=False).stdout
    return hashlib.sha256(archive).hexdigest()


def verify_source(source: Path, experiment: dict[str, Any]) -> Path:
    expected_revision = experiment["repository"]["revision"]
    actual_revision = git_command(source, "rev-parse", "HEAD").stdout.strip()
    if actual_revision != expected_revision:
        raise RuntimeError(
            f"fastText revision mismatch: expected {expected_revision}, got {actual_revision}"
        )
    status = git_command(source, "status", "--short").stdout.strip()
    if status:
        raise RuntimeError("fastText source checkout must be clean")
    expected_archive = experiment["repository"]["archive_sha256"]
    actual_archive = source_archive_sha256(source)
    if actual_archive != expected_archive:
        raise RuntimeError(
            f"fastText source archive mismatch: expected {expected_archive}, got {actual_archive}"
        )
    return source.resolve()


def ensure_source(
    experiment: dict[str, Any], cache_dir: Path, supplied_checkout: Path | None
) -> Path:
    if supplied_checkout is not None:
        return verify_source(supplied_checkout.resolve(), experiment)
    source = cache_dir / "fastText"
    if source.exists():
        return verify_source(source, experiment)
    source.parent.mkdir(parents=True, exist_ok=True)
    clone = ["git"]
    if os.name == "nt":
        clone.extend(["-c", "http.sslBackend=schannel"])
    clone.extend(
        [
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            experiment["repository"]["url"],
            str(source),
        ]
    )
    run_command(clone)
    git_command(source, "fetch", "--depth=1", "origin", experiment["repository"]["revision"])
    git_command(source, "checkout", "--detach", experiment["repository"]["revision"])
    return verify_source(source, experiment)


def copy_source_for_build(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )


def build_image(
    experiment: dict[str, Any], source: Path, cache_dir: Path, image_tag: str
) -> dict[str, str]:
    build_root = cache_dir / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fasttext-", dir=build_root) as temporary:
        context = Path(temporary)
        copy_source_for_build(source, context / "fastText")
        shutil.copy2(EXAMPLE_DIR / "Dockerfile", context / "Dockerfile")
        shutil.copy2(EXAMPLE_DIR / "container_runner.py", context / "container_runner.py")
        revision = experiment["repository"]["revision"]
        # Keep this marker byte-identical on Windows and POSIX so the image
        # build can reject a source/context mismatch before compilation.
        (context / "SOURCE_REVISION").write_bytes(revision.encode("ascii"))
        print(f"Building frozen experiment image: {image_tag}", flush=True)
        run_command(
            [
                "docker",
                "build",
                "--pull=false",
                "--build-arg",
                f"SOURCE_REVISION={revision}",
                "--label",
                f"org.opencontainers.image.revision={revision}",
                "--label",
                f"org.repropilot.experiment={experiment['id']}",
                "-t",
                image_tag,
                str(context),
            ],
            capture_output=False,
        )
    inspected = run_command(
        [
            "docker",
            "image",
            "inspect",
            image_tag,
            "--format",
            "{{.Id}}|{{.Created}}",
        ]
    ).stdout.strip()
    image_id, created = inspected.split("|", 1)
    return {"tag": image_tag, "id": image_id, "created": created}


def execute_container(
    experiment: dict[str, Any], dataset_archive: Path, image_tag: str
) -> tuple[dict[str, Any], list[str]]:
    environment = experiment["environment"]
    seeds = ",".join(str(seed) for seed in experiment["protocol"]["shuffle_seeds"])
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        str(environment["cpus"]),
        "--memory",
        environment["memory"],
        "--pids-limit",
        str(environment["pids_limit"]),
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--user",
        "65534:65534",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,size={environment['tmpfs_size']}",
        "--mount",
        f"type=bind,src={dataset_archive},dst=/input/ag_news_csv.tgz,readonly",
        image_tag,
        "--seeds",
        seeds,
    ]
    print("Running frozen experiment with container network disabled", flush=True)
    completed = run_command(command)
    metrics = json.loads(completed.stdout)
    if metrics.get("status") != "completed":
        raise RuntimeError("experiment container did not return completed metrics")
    public_command = [
        item.replace(str(dataset_archive), "<DATASET_ARCHIVE>") for item in command
    ]
    return metrics, public_command


def criterion_status_absolute(observed: float, expected: float, tolerance: float) -> str:
    distance = abs(observed - expected)
    if distance <= tolerance:
        return "verified"
    if distance <= tolerance * 2:
        return "partially_reproduced"
    return "contradicted"


def criterion_status_gain(observed: float, minimum: float) -> str:
    if observed >= minimum:
        return "verified"
    if observed > 0:
        return "partially_reproduced"
    return "contradicted"


def adjudicate(
    experiment: dict[str, Any], metrics: dict[str, Any], provenance: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paper = experiment["paper"]
    claim = experiment["claim"]
    summary = metrics["summary"]
    observed_accuracy = float(summary["bigram"]["mean_accuracy_percent"])
    observed_gain = float(summary["bigram_gain_percentage_points"])
    expected_accuracy = float(paper["reported"]["bigram_accuracy_percent"])
    tolerance = float(claim["absolute_accuracy_tolerance_percentage_points"])
    minimum_gain = float(claim["minimum_bigram_gain_percentage_points"])
    absolute_status = criterion_status_absolute(observed_accuracy, expected_accuracy, tolerance)
    gain_status = criterion_status_gain(observed_gain, minimum_gain)

    rubric = normalize_rubric(
        ClaimRubric(
            paper_title=paper["title"],
            claims=[
                PaperClaim(
                    title="Word bigrams improve AG News accuracy",
                    statement=claim["statement"],
                    source_locator=paper["source_locator"],
                    claim_type="ablation",
                    importance=1.0,
                    criteria=[
                        ClaimCriterion(
                            description=(
                                "Mean bigram test accuracy is within the frozen tolerance of "
                                "the paper's 92.5% AG News result."
                            ),
                            metric_name="bigram_mean_accuracy_percent",
                            expected_value=expected_accuracy,
                            tolerance=tolerance,
                            unit="percent",
                            required_evidence=["paper", "repository", "environment", "metric"],
                        ),
                        ClaimCriterion(
                            description=(
                                "The bigram variant improves mean test accuracy over the unigram "
                                "control by at least 0.5 percentage points."
                            ),
                            metric_name="bigram_gain_percentage_points",
                            expected_value=float(paper["reported"]["bigram_gain_percentage_points"]),
                            tolerance=0.5,
                            unit="percentage_points",
                            required_evidence=["paper", "run", "metric", "comparison"],
                        ),
                    ],
                )
            ],
        )
    )
    comparison = {
        "version": "repropilot.paper-comparison/v1",
        "paper_reported": paper["reported"],
        "observed": summary,
        "criteria": {
            "absolute_accuracy": {
                "status": absolute_status,
                "expected_percent": expected_accuracy,
                "observed_percent": observed_accuracy,
                "tolerance_percentage_points": tolerance,
            },
            "bigram_gain": {
                "status": gain_status,
                "paper_reported_percentage_points": paper["reported"]["bigram_gain_percentage_points"],
                "minimum_percentage_points": minimum_gain,
                "observed_percentage_points": observed_gain,
            },
        },
        "protocol_deviations": experiment["protocol"]["protocol_deviations"],
    }
    parsed_paper = {
        "title": paper["title"],
        "arxiv_id": paper["arxiv_id"],
        "source_locator": paper["source_locator"],
        "claim": claim["statement"],
        "reported": paper["reported"],
        "pdf_sha256": paper["pdf_sha256"],
    }
    repo_manifest = {
        "url": experiment["repository"]["url"],
        "revision": experiment["repository"]["revision"],
        "archive_sha256": experiment["repository"]["archive_sha256"],
        "license": experiment["repository"]["license"],
        "additional_patent_grant": experiment["repository"].get("additional_patent_grant", ""),
    }
    artifacts = {
        "parsed_paper": canonical_json(parsed_paper),
        "repo_manifest": canonical_json(repo_manifest),
        "reproduction_mode_report": canonical_json(
            {
                "mode": "bounded_claim_reproduction",
                "container": provenance["container"],
                "protocol_deviations": experiment["protocol"]["protocol_deviations"],
            }
        ),
        "dependency_install_report": canonical_json(
            {"base_image": experiment["environment"]["base_image"], "fasttext_source": repo_manifest}
        ),
        "run_metrics": canonical_json(metrics),
        "paper_debug_report": canonical_json(
            {"status": "not_needed", "patches": 0, "source_revision_unchanged": True}
        ),
        "paper_patch_manifest": "[]",
        "comparison_report": canonical_json(comparison),
    }
    proposal = {
        "findings": [
            {
                "claim_id": "claim-001",
                "criterion_id": "claim-001.criterion-01",
                "status": absolute_status,
                "confidence": 1.0,
                "observed_value": f"{observed_accuracy:.3f}% mean across {summary['bigram']['runs']} runs",
                "evidence_keys": [
                    "parsed_paper",
                    "repo_manifest",
                    "reproduction_mode_report",
                    "run_metrics",
                    "comparison_report",
                ],
                "reason": (
                    f"Observed {observed_accuracy:.3f}% versus paper {expected_accuracy:.1f}% "
                    f"with a frozen +/-{tolerance:.1f} percentage-point tolerance."
                ),
            },
            {
                "claim_id": "claim-001",
                "criterion_id": "claim-001.criterion-02",
                "status": gain_status,
                "confidence": 1.0,
                "observed_value": f"{observed_gain:.3f} percentage points",
                "evidence_keys": ["parsed_paper", "run_metrics", "comparison_report"],
                "reason": (
                    f"Observed paired mean gain {observed_gain:.3f} percentage points; "
                    f"the frozen minimum is {minimum_gain:.1f}."
                ),
            },
        ]
    }
    graph = build_evidence_graph(rubric, proposal, artifacts)
    return (
        rubric.model_dump(mode="json"),
        comparison,
        graph.model_dump(mode="json"),
    )


def render_report(
    experiment: dict[str, Any], metrics: dict[str, Any], comparison: dict[str, Any], graph: dict[str, Any]
) -> str:
    summary = metrics["summary"]
    claim = graph["claims"][0]
    rows = []
    by_seed: dict[int, dict[str, float]] = {}
    for trial in metrics["trials"]:
        by_seed.setdefault(int(trial["shuffle_seed"]), {})[trial["variant"]] = float(
            trial["accuracy_percent"]
        )
    for seed, values in sorted(by_seed.items()):
        rows.append(
            f"| {seed} | {values['unigram']:.3f}% | {values['bigram']:.3f}% | "
            f"{values['bigram'] - values['unigram']:.3f} pp |"
        )
    return f"""# fastText AG News bounded reproduction

## Verdict

**{claim['status']}** - {claim['statement']}

This result covers one frozen claim from Table 1 and Section 3.1 of *Bag of Tricks for Efficient Text Classification*. It is not a reproduction of every dataset, timing result, or conclusion in the paper.

## Observed results

| Shuffle seed | Unigram accuracy | Bigram accuracy | Gain |
|---:|---:|---:|---:|
{chr(10).join(rows)}

- Mean unigram accuracy: `{summary['unigram']['mean_accuracy_percent']:.3f}%`
- Mean bigram accuracy: `{summary['bigram']['mean_accuracy_percent']:.3f}%`
- Mean bigram gain: `{summary['bigram_gain_percentage_points']:.3f}` percentage points
- Paper values: `91.5%` unigram and `92.5%` bigram
- Frozen absolute tolerance: `+/-{experiment['claim']['absolute_accuracy_tolerance_percentage_points']:.1f}` percentage points
- Frozen minimum gain: `{experiment['claim']['minimum_bigram_gain_percentage_points']:.1f}` percentage points

## Frozen inputs

- Paper: arXiv `{experiment['paper']['arxiv_id']}`, PDF SHA-256 `{experiment['paper']['pdf_sha256']}`
- Source: `{experiment['repository']['url']}` at `{experiment['repository']['revision']}`
- Source archive SHA-256: `{experiment['repository']['archive_sha256']}`
- Dataset archive SHA-256: `{experiment['dataset']['archive_sha256']}`
- Base image: `{experiment['environment']['base_image']}`
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

{chr(10).join(f'- {item}' for item in experiment['protocol']['protocol_deviations'])}
- Accuracy agreement under this protocol does not establish exact equivalence to the authors' 2016 hardware, compiler, or asynchronous thread schedule.
- The dataset is downloaded at run time and is not redistributed by ReproPilot.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=REPOSITORY_ROOT / "tmp" / "paper-reproduction-cache")
    parser.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--source-checkout", type=Path)
    parser.add_argument("--image-tag", default="repropilot-fasttext-ag-news:paper-v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = datetime.now(timezone.utc)
    experiment = load_experiment(EXAMPLE_DIR / "experiment.json")
    cache_dir = args.cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_archive = ensure_dataset(experiment, cache_dir, args.dataset_archive)
    source = ensure_source(experiment, cache_dir, args.source_checkout)
    image = build_image(experiment, source, cache_dir, args.image_tag)
    metrics, docker_command = execute_container(experiment, dataset_archive, args.image_tag)
    finished = datetime.now(timezone.utc)
    docker_version = run_command(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip()
    repropilot_revision = run_command(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"]
    ).stdout.strip()
    provenance = {
        "version": "repropilot.paper-provenance/v1",
        "experiment_id": experiment["id"],
        "experiment_spec_sha256": sha256_text(canonical_json(experiment)),
        "repropilot_revision": repropilot_revision,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "host_platform": platform.platform(),
        "source": experiment["repository"],
        "dataset": {
            "url": experiment["dataset"]["url"],
            "archive_sha256": experiment["dataset"]["archive_sha256"],
            "train_sha256": experiment["dataset"]["train_sha256"],
            "test_sha256": experiment["dataset"]["test_sha256"],
        },
        "container": {
            "docker_server_version": docker_version,
            "image": image,
            "base_image": experiment["environment"]["base_image"],
            "network": "none",
            "read_only_root": True,
            "capabilities_dropped": "ALL",
            "no_new_privileges": True,
            "resource_limits": experiment["environment"],
            "command": docker_command,
        },
    }
    rubric, comparison, graph = adjudicate(experiment, metrics, provenance)

    outputs: dict[str, Any] = {
        "experiment-spec.json": experiment,
        "run-metrics.json": metrics,
        "comparison-report.json": comparison,
        "claim-rubric.json": rubric,
        "claim-evidence-graph.json": graph,
        "provenance.json": provenance,
    }
    for name, value in outputs.items():
        write_json(output_dir / name, value)
    report = render_report(experiment, metrics, comparison, graph)
    (output_dir / "README.md").write_text(report, encoding="utf-8", newline="\n")

    evidence_files = sorted([*outputs, "README.md"])
    bundle = {
        "version": "repropilot.paper-evidence-bundle/v1",
        "experiment_id": experiment["id"],
        "verdict": graph["claims"][0]["status"],
        "files": {
            name: {"sha256": sha256_file(output_dir / name), "bytes": (output_dir / name).stat().st_size}
            for name in evidence_files
        },
    }
    write_json(output_dir / "evidence-bundle.json", bundle)
    print(
        json.dumps(
            {
                "status": "completed",
                "verdict": bundle["verdict"],
                "output_dir": str(output_dir),
                "bigram_accuracy_percent": metrics["summary"]["bigram"]["mean_accuracy_percent"],
                "bigram_gain_percentage_points": metrics["summary"]["bigram_gain_percentage_points"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
