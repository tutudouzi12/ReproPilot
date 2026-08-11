from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable


IMPORT_TO_PACKAGE = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "llama_index": "llama-index",
    "langchain_community": "langchain-community",
    "sentence_transformers": "sentence-transformers",
}
SKIPPED_DIRECTORIES = {".git", ".repropilot", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", "docs"}


def resolve_python_dependencies(code: str, workspace: str = "", code_file_path: str = "") -> list[str]:
    direct = detect_python_dependencies(code)
    if Path(code_file_path).name.lower() == "repropilot_smoke.py":
        return normalize_dependencies(direct)
    workspace_path = Path(workspace) if workspace else None
    detected = list(direct)
    repository = []
    if workspace_path and workspace_path.is_dir():
        workspace_dependencies = filter_workspace_local_dependencies(
            detect_workspace_python_dependencies(workspace_path), workspace_path
        )
        detected.extend(workspace_dependencies)
        repository = detect_repository_dependencies(workspace_path)
        roots = dependency_roots([*workspace_dependencies, *direct])
        if roots:
            repository = [item for item in repository if package_root(item) in roots]
        detected.extend(repository)
        detected = filter_workspace_local_dependencies(detected, workspace_path)
    return normalize_dependencies(detected)


def detect_python_dependencies(code: str) -> list[str]:
    if not code.strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return sorted(
        {IMPORT_TO_PACKAGE.get(module, module) for module in modules if module not in sys.stdlib_module_names and module != "__future__"},
        key=str.lower,
    )


def detect_workspace_python_dependencies(workspace: str | Path, max_files: int = 500) -> list[str]:
    root = Path(workspace).resolve(strict=True)
    dependencies: list[str] = []
    count = 0
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part.lower() in SKIPPED_DIRECTORIES for part in relative.parts) or path.is_symlink() or not path.is_file():
            continue
        dependencies.extend(detect_python_dependencies(path.read_text(encoding="utf-8", errors="replace")[:512_000]))
        count += 1
        if count >= max_files:
            break
    return _unique(dependencies)


def detect_repository_dependencies(workspace: str | Path) -> list[str]:
    root = Path(workspace).resolve(strict=True)
    dependencies: list[str] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            dependencies.extend(_requirements(path.read_text(encoding="utf-8", errors="replace")))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        dependencies.extend(_quoted_dependencies(pyproject.read_text(encoding="utf-8", errors="replace")))
    return _unique(dependencies)


def filter_workspace_local_dependencies(dependencies: Iterable[str], workspace: str | Path) -> list[str]:
    local = workspace_module_roots(workspace)
    return [dependency for dependency in dependencies if package_root(dependency).replace("-", "_") not in local]


def workspace_module_roots(workspace: str | Path) -> set[str]:
    root = Path(workspace).resolve(strict=True)
    modules: set[str] = set()
    search_roots = [root]
    if (root / "src").is_dir():
        search_roots.append(root / "src")
    for search_root in search_roots:
        for child in search_root.iterdir():
            if child.name.startswith(".") or child.name in SKIPPED_DIRECTORIES or child.is_symlink():
                continue
            if child.is_file() and child.suffix == ".py":
                modules.add(child.stem.lower())
            elif child.is_dir() and ((child / "__init__.py").is_file() or any(child.glob("*.py"))):
                modules.add(child.name.lower())
    return modules


def normalize_dependencies(items: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in items:
        value = raw.strip()
        if not value or value.startswith(("-", "#")):
            continue
        root = package_root(value)
        if root in {"python", "tensorflow"} and (root == "python" or _legacy_tensorflow(value)):
            continue
        if root == "pytorch":
            value = "torch"
        elif root == "msgpack-python":
            value = "msgpack"
        normalized.append(value)
        if package_root(value) == "langchain":
            normalized.append("langchain-community")
    return _unique(normalized)


def package_root(value: str) -> str:
    stripped = re.split(r"[<>=!~;\[\s]", value.strip(), maxsplit=1)[0]
    return stripped.lower().replace("_", "-")


def dependency_roots(items: Iterable[str]) -> set[str]:
    return {package_root(item) for item in items if package_root(item)}


def _requirements(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        value = line.split("#", 1)[0].strip()
        if value and not value.startswith(("-r", "--", "git+", "http://", "https://")):
            result.append(value)
    return result


def _quoted_dependencies(text: str) -> list[str]:
    result = []
    in_dependencies = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "[" in stripped:
            in_dependencies = True
        if in_dependencies:
            result.extend(re.findall(r"[\"']([^\"']+)[\"']", stripped))
            if "]" in stripped:
                in_dependencies = False
    return result


def _legacy_tensorflow(value: str) -> bool:
    match = re.search(r"tensorflow\s*==\s*(\d+)", value, re.IGNORECASE)
    return bool(match and int(match.group(1)) < 2)


def _unique(items: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result
