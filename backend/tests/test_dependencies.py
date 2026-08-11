from __future__ import annotations

from app.dependencies import (
    detect_python_dependencies,
    filter_workspace_local_dependencies,
    normalize_dependencies,
    resolve_python_dependencies,
)


def test_detect_python_dependencies_filters_expanded_standard_library():
    code = """
from __future__ import annotations
import inspect
import codecs
import glob
import urllib.request
import tarfile
import torch
from sklearn.metrics import accuracy_score
"""
    assert detect_python_dependencies(code) == ["scikit-learn", "torch"]


def test_workspace_local_modules_are_not_treated_as_pip_packages(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    for name in ("config.py", "learner.py", "scheduler.py", "dataset.py", "callbacks.py"):
        (source / name).write_text("# local module\n", encoding="utf-8")
    (source / "architectures").mkdir()
    (source / "architectures" / "__init__.py").write_text("", encoding="utf-8")

    filtered = filter_workspace_local_dependencies(
        ["torch", "wandb", "config", "learner", "scheduler", "dataset", "callbacks", "architectures", "numpy"],
        tmp_path,
    )
    assert filtered == ["torch", "wandb", "numpy"]


def test_legacy_paper_dependencies_are_normalized_for_modern_python():
    assert normalize_dependencies(
        ["python==3.6.12", "pytorch==1.3.1", "msgpack-python==1.0.2", "tensorflow==1.14.0", "numpy"]
    ) == ["torch", "msgpack", "numpy"]


def test_smoke_runner_ignores_heavy_repository_scripts(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    smoke = workspace / "repropilot_smoke.py"
    smoke.write_text("import json\nimport torch\n", encoding="utf-8")
    (workspace / "src" / "train.py").write_text("import wandb\nfrom datasets import load_dataset\n", encoding="utf-8")
    (workspace / "requirements.txt").write_text("torch\nwandb\ndatasets\n", encoding="utf-8")

    dependencies = resolve_python_dependencies(smoke.read_text(encoding="utf-8"), str(workspace), str(smoke))

    assert dependencies == ["torch"]


def test_framework_plugin_imports_map_to_distribution_names():
    code = """
from llama_index.core import VectorStoreIndex
from langchain_community.vectorstores import FAISS
from sentence_transformers import SentenceTransformer
"""
    assert detect_python_dependencies(code) == ["langchain-community", "llama-index", "sentence-transformers"]
