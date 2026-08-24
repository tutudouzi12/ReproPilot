from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


MAVEN_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <mirrors>
    <mirror>
      <id>repropilot-maven-central</id>
      <name>Maven Central over HTTPS</name>
      <url>https://repo.maven.apache.org/maven2</url>
      <mirrorOf>*</mirrorOf>
    </mirror>
  </mirrors>
</settings>
"""


@dataclass(frozen=True)
class Case:
    name: str
    input_value: str
    name_type: str
    rule_type: str
    concat: bool
    max_phonemes: int
    expected: str | None = None


PUBLIC_CASES = [
    Case("triple_apostrophe", "'''", "SEPHARDIC", "APPROX", False, 10, ""),
    Case("single_apostrophe", "'", "SEPHARDIC", "APPROX", False, 10, ""),
    Case("generic_da_control", "da", "GENERIC", "EXACT", False, 10, "da|di"),
    Case("ordinary_name_control", "smith", "GENERIC", "APPROX", False, 10),
]


def _run(
    command: list[str],
    timeout_seconds: float,
    environment: dict[str, str] | None = None,
    working_directory: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=working_directory or Path.cwd(),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": f"{exc.stderr or ''}\ncommand timed out after {timeout_seconds:.2f}s".strip(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def _maven(
    arguments: list[str],
    timeout_seconds: float,
    working_directory: Path,
) -> dict[str, Any]:
    executable = shutil.which("mvn")
    javac = shutil.which("javac")
    if executable is None or javac is None:
        raise RuntimeError("Maven and a JDK compiler are required on PATH")
    java_home = Path(javac).resolve().parent.parent
    environment = os.environ.copy()
    environment["JAVA_HOME"] = str(java_home)
    environment["PATH"] = str(java_home / "bin") + os.pathsep + environment.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="repropilot-maven-settings-") as temporary:
        settings = Path(temporary) / "settings.xml"
        settings.write_text(MAVEN_SETTINGS, encoding="utf-8", newline="\n")
        return _run(
            [
                executable,
                "-gs",
                str(settings),
                "-s",
                str(settings),
                "-q",
                "-Drat.skip=true",
                *arguments,
            ],
            timeout_seconds,
            environment,
            working_directory,
        )


@contextmanager
def _isolated_workspace() -> Iterator[Path]:
    source = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="rp-codec-") as temporary:
        workspace = Path(temporary) / "repo"
        shutil.copytree(
            source,
            workspace,
            ignore=shutil.ignore_patterns(".git", ".repropilot", "target"),
        )
        yield workspace


def _java_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _probe_source(cases: list[Case]) -> str:
    statements: list[str] = []
    for case in cases:
        expected = "null" if case.expected is None else _java_literal(case.expected)
        statements.append(
            "run("
            f"{_java_literal(case.name)}, "
            f"{_java_literal(case.input_value)}, "
            f"NameType.{case.name_type}, RuleType.{case.rule_type}, "
            f"{str(case.concat).lower()}, {case.max_phonemes}, {expected});"
        )
    body = "\n        ".join(statements)
    return f"""import org.apache.commons.codec.language.bm.NameType;
import org.apache.commons.codec.language.bm.PhoneticEngine;
import org.apache.commons.codec.language.bm.RuleType;

public final class ReproPilotCodecProbe {{
    private static String clean(String value) {{
        return value.replace('\\t', ' ').replace('\\n', ' ').replace('\\r', ' ');
    }}

    private static void run(String name, String input, NameType nameType, RuleType ruleType,
                            boolean concat, int maxPhonemes, String expected) {{
        try {{
            PhoneticEngine engine = new PhoneticEngine(nameType, ruleType, concat, maxPhonemes);
            String observed = engine.encode(input);
            if (observed == null) {{
                throw new AssertionError("returned null");
            }}
            if (expected != null && !expected.equals(observed)) {{
                throw new AssertionError("expected=" + expected + " observed=" + observed);
            }}
            System.out.println(name + "\\ttrue\\t" + clean(observed));
        }} catch (Throwable error) {{
            System.out.println(name + "\\tfalse\\t" + clean(error.getClass().getSimpleName() + ": " + error.getMessage()));
        }}
    }}

    public static void main(String[] arguments) {{
        {body}
    }}
}}
"""


def _evaluate_cases(cases: list[Case], workspace: Path) -> dict[str, Any]:
    compile_result = _maven(
        ["-DskipTests", "compile"],
        timeout_seconds=300,
        working_directory=workspace,
    )
    if compile_result["exit_code"] != 0:
        raise RuntimeError(compile_result["stderr"] or compile_result["stdout"] or "Maven compile failed")

    javac = shutil.which("javac")
    java = shutil.which("java")
    if javac is None or java is None:
        raise RuntimeError("Java compiler and runtime are required on PATH")
    classes = (workspace / "target" / "classes").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="repropilot-codec-probe-") as temporary:
        probe_root = Path(temporary)
        source = probe_root / "ReproPilotCodecProbe.java"
        source.write_text(_probe_source(cases), encoding="utf-8", newline="\n")
        compile_probe = _run(
            [javac, "-encoding", "UTF-8", "-cp", str(classes), "-d", str(probe_root), str(source)],
            timeout_seconds=60,
            working_directory=workspace,
        )
        if compile_probe["exit_code"] != 0:
            raise RuntimeError(compile_probe["stderr"] or compile_probe["stdout"] or "Java probe compile failed")
        run_probe = _run(
            [java, "-cp", os.pathsep.join([str(probe_root), str(classes)]), "ReproPilotCodecProbe"],
            timeout_seconds=60,
            working_directory=workspace,
        )
        if run_probe["exit_code"] != 0:
            raise RuntimeError(run_probe["stderr"] or run_probe["stdout"] or "Java probe failed")

    observed: dict[str, dict[str, Any]] = {}
    for line in run_probe["stdout"].splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            name, passed, detail = parts
            observed[name] = {"name": name, "passed": passed == "true", "observed": detail}
    results = [observed.get(case.name, {"name": case.name, "passed": False, "error": "missing probe result"}) for case in cases]
    passed = sum(bool(result["passed"]) for result in results)
    return {
        "passed": passed,
        "total": len(results),
        "cases": results,
        "build": {"maven_compile_duration_ms": compile_result["duration_ms"]},
        "metrics": {"phonetic_boundary_score": passed / len(results)},
    }


def evaluate_cases(cases: list[Case]) -> dict[str, Any]:
    with _isolated_workspace() as workspace:
        return _evaluate_cases(cases, workspace)


def upstream_checks() -> dict[str, Any]:
    with _isolated_workspace() as workspace:
        result = _maven(["test"], timeout_seconds=330, working_directory=workspace)
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        if result["exit_code"] == 0:
            for report in sorted((workspace / "target" / "surefire-reports").glob("TEST-*.xml")):
                attributes = ET.parse(report).getroot().attrib
                for key in totals:
                    totals[key] += int(float(attributes.get(key, "0")))
    payload: dict[str, Any] = {
        "upstream_checks_passed": result["exit_code"] == 0,
        "command": ["mvn", "-q", "-Drat.skip=true", "test"],
        "exit_code": result["exit_code"],
        "duration_ms": result["duration_ms"],
        "surefire": totals,
    }
    if result["exit_code"] != 0:
        payload["stdout_tail"] = result["stdout"][-4000:]
        payload["stderr_tail"] = result["stderr"][-4000:]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", action="store_true")
    args = parser.parse_args()
    if args.upstream:
        payload = upstream_checks()
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["upstream_checks_passed"] else 1
    print(json.dumps(evaluate_cases(PUBLIC_CASES), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
