#!/usr/bin/env python3
"""Run the frozen fastText AG News comparison inside the experiment container."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import statistics
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any


EXPECTED_MEMBERS = {
    "ag_news_csv/train.csv": "76a0a2d2f92b286371fe4d4044640910a04a803fdd2538e0f3f29a5c6f6b672e",
    "ag_news_csv/test.csv": "521465c2428ed7f02f8d6db6ffdd4b5447c1c701962353eb2c40d548c3c85699",
    "ag_news_csv/readme.txt": "779c2e6bbf93dd810d9c7b318006daef7a4bfc34062002461d251dc10fb9f58c",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_verified_members(archive: Path) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member_name, expected_hash in EXPECTED_MEMBERS.items():
            member = bundle.getmember(member_name)
            if not member.isfile():
                raise RuntimeError(f"dataset member is not a regular file: {member_name}")
            stream = bundle.extractfile(member)
            if stream is None:
                raise RuntimeError(f"dataset member is unreadable: {member_name}")
            value = stream.read()
            actual_hash = sha256_bytes(value)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"dataset member SHA-256 mismatch for {member_name}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )
            values[member_name] = value
    return values


def normalize_line(raw: str) -> str:
    """Reproduce fastText classification-results.sh normalization exactly."""
    value = "__label__" + raw.lower()
    value = value.replace("'", " ' ")
    value = value.replace('"', "")
    value = value.replace(".", " . ")
    value = value.replace("<br />", " ")
    value = value.replace(",", " , ")
    value = value.replace("(", " ( ")
    value = value.replace(")", " ) ")
    value = value.replace("!", " ! ")
    value = value.replace("?", " ? ")
    value = value.replace(";", " ")
    value = value.replace(":", " ")
    return " ".join(value.split())


def prepare_dataset(raw: bytes, output: Path, seed: int) -> int:
    lines = [normalize_line(line) for line in raw.decode("utf-8").splitlines()]
    random.Random(seed).shuffle(lines)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def parse_test_output(output: str) -> tuple[int, float]:
    count_match = re.search(
        r"^(?:N\s+|Number of examples:\s*)(\d+)\s*$", output, re.MULTILINE
    )
    precision_match = re.search(r"^P@1(?:\s+|:\s*)([0-9.]+)\s*$", output, re.MULTILINE)
    if not count_match or not precision_match:
        raise RuntimeError(f"unexpected fastText test output: {output[:500]!r}")
    return int(count_match.group(1)), float(precision_match.group(1)) * 100.0


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        stdout = " ".join(completed.stdout.split())[:1000]
        stderr = " ".join(completed.stderr.split())[:1000]
        raise RuntimeError(
            f"experiment command failed with exit code {completed.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    return completed


def run_variant(
    *,
    train_file: Path,
    test_file: Path,
    work_dir: Path,
    variant: str,
    word_ngrams: int,
    seed: int,
) -> dict[str, Any]:
    model_prefix = work_dir / f"model-{variant}-{seed}"
    command = [
        "/usr/local/bin/fasttext",
        "supervised",
        "-input",
        str(train_file),
        "-output",
        str(model_prefix),
        "-dim",
        "10",
        "-lr",
        "0.25",
        "-wordNgrams",
        str(word_ngrams),
        "-minCount",
        "1",
        "-bucket",
        "10000000",
        "-epoch",
        "5",
        "-thread",
        "4",
    ]
    started = time.perf_counter()
    completed = run_checked(command)
    training_seconds = time.perf_counter() - started
    test = run_checked(
        ["/usr/local/bin/fasttext", "test", f"{model_prefix}.bin", str(test_file)]
    )
    test_examples, accuracy_percent = parse_test_output(test.stdout)
    model_bytes = Path(f"{model_prefix}.bin").stat().st_size
    for suffix in (".bin", ".vec"):
        Path(f"{model_prefix}{suffix}").unlink(missing_ok=True)
    return {
        "variant": variant,
        "word_ngrams": word_ngrams,
        "shuffle_seed": seed,
        "accuracy_percent": round(accuracy_percent, 6),
        "test_examples": test_examples,
        "training_seconds": round(training_seconds, 6),
        "model_bytes": model_bytes,
        "training_stdout_sha256": sha256_bytes(completed.stdout.encode("utf-8")),
        "training_stderr_sha256": sha256_bytes(completed.stderr.encode("utf-8")),
    }


def summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {"unigram": [], "bigram": []}
    for trial in trials:
        by_variant[trial["variant"]].append(trial)
    summary: dict[str, Any] = {}
    for variant, rows in by_variant.items():
        accuracies = [float(row["accuracy_percent"]) for row in rows]
        runtimes = [float(row["training_seconds"]) for row in rows]
        summary[variant] = {
            "runs": len(rows),
            "mean_accuracy_percent": round(statistics.fmean(accuracies), 6),
            "min_accuracy_percent": round(min(accuracies), 6),
            "max_accuracy_percent": round(max(accuracies), 6),
            "population_stddev_percentage_points": round(statistics.pstdev(accuracies), 6),
            "mean_training_seconds": round(statistics.fmean(runtimes), 6),
        }
    summary["bigram_gain_percentage_points"] = round(
        summary["bigram"]["mean_accuracy_percent"]
        - summary["unigram"]["mean_accuracy_percent"],
        6,
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("/input/ag_news_csv.tgz"))
    parser.add_argument("--seeds", default="1729,2718,3141")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seeds = [int(value) for value in args.seeds.split(",") if value]
    if not seeds or len(set(seeds)) != len(seeds):
        raise SystemExit("shuffle seeds must be non-empty and unique")
    members = read_verified_members(args.dataset)
    work_dir = Path("/tmp/fasttext-reproduction")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    trials: list[dict[str, Any]] = []
    for seed in seeds:
        train_file = work_dir / f"train-{seed}.txt"
        test_file = work_dir / f"test-{seed}.txt"
        train_examples = prepare_dataset(members["ag_news_csv/train.csv"], train_file, seed)
        test_examples = prepare_dataset(members["ag_news_csv/test.csv"], test_file, seed)
        if train_examples != 120000 or test_examples != 7600:
            raise RuntimeError(
                f"unexpected dataset cardinality: train={train_examples}, test={test_examples}"
            )
        for variant, word_ngrams in (("unigram", 1), ("bigram", 2)):
            trials.append(
                run_variant(
                    train_file=train_file,
                    test_file=test_file,
                    work_dir=work_dir,
                    variant=variant,
                    word_ngrams=word_ngrams,
                    seed=seed,
                )
            )
        train_file.unlink()
        test_file.unlink()
    payload = {
        "version": "repropilot.paper-run-metrics/v1",
        "status": "completed",
        "source_revision": Path("/opt/repropilot/SOURCE_REVISION").read_text(encoding="utf-8").strip(),
        "dataset_members": EXPECTED_MEMBERS,
        "fasttext_binary_sha256": sha256_file(Path("/usr/local/bin/fasttext")),
        "toolchain": {
            "python": subprocess.run(
                ["python3", "--version"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "compiler": subprocess.run(
                ["g++", "--version"], check=True, capture_output=True, text=True
            ).stdout.splitlines()[0],
        },
        "trials": trials,
        "summary": summarize(trials),
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
