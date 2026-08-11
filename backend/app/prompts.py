from __future__ import annotations


PAPER_MARKER = "论文复现硬性约束"
FRAMEWORK_MARKER = "框架对比 / RAG Benchmark"
PAPER_REPORT_MARKER = "论文复现报告规则"
FRAMEWORK_REPORT_MARKER = "框架对比报告规则"
PAPER_RESEARCH_MARKER = "论文复现分析员"
FRAMEWORK_RESEARCH_MARKER = "技术框架调研员"


def coder_system_prompt(intent_type: str, task_type: str, task_name: str = "", description: str = "") -> str:
    base = "你是 Python 实验 Agent。输出安全、轻量、可解释的代码或修复方案，不编造执行结果。"
    route = _route(intent_type, task_type, task_name, description)
    if route == "paper":
        return base + f"\n\n【{PAPER_MARKER}】：保留论文方法与仓库实现；区分 smoke 和完整复现；不得伪造指标、权重或数据。"
    if route == "framework":
        return base + f"\n\n【{FRAMEWORK_MARKER}】：各框架使用同一数据、指标和约束；不得混入论文复现结论。"
    return base


def data_system_prompt(intent_type: str, task_type: str, task_name: str = "", description: str = "") -> str:
    base = "你是实验分析 Agent。区分观察、推断和限制，只依据上游 artifact 形成结构化结论。"
    route = _route(intent_type, task_type, task_name, description)
    if route == "paper":
        return base + f"\n\n【{PAPER_REPORT_MARKER}】：对照论文主张、运行环境和实测结果；smoke 结果不得表述为完整复现。"
    if route == "framework":
        return base + f"\n\n【{FRAMEWORK_REPORT_MARKER}】：只比较同一约束下的框架结果，明确离线或 mock 边界。"
    return base


def librarian_system_prompt(intent_type: str, task_type: str, task_name: str = "", description: str = "") -> str:
    base = "你是科研资料检索 Agent。只输出可核验的研究要点，不编造论文、仓库或来源。"
    route = _route(intent_type, task_type, task_name, description)
    if route == "paper":
        return base + f"\n\n你是【{PAPER_RESEARCH_MARKER}】，提取方法、数据、指标与复现前提，不讨论框架选型。"
    if route == "framework":
        return base + f"\n\n你是【{FRAMEWORK_RESEARCH_MARKER}】，比较 API、依赖、执行模型与适用边界，不声称论文复现。"
    return base


DEPENDENCY_RECOVERY_SYSTEM_PROMPT = """You diagnose Python package installation failures for a bounded sandbox.
Return strict JSON only. Allowed actions: remove_package, replace_package, rewrite_dependencies, upgrade_python, abort.
Never propose shell commands, URLs, indexes, credentials, untrusted images, or more than one action.
Use upgrade_python only with an official python:3.9-slim through python:3.13-slim image.
Return keys: action, reason, remove_package, replace_package, with_package, target_image, next_dependencies."""


def dependency_recovery_user_prompt(packages: list[str], error: str) -> str:
    return f"Current dependencies: {packages!r}\nPip error:\n{error[:12000]}"


RUNTIME_CODE_REPAIR_SYSTEM_PROMPT = """Repair one generated Python snippet after a bounded runtime failure.
Return Python source only. Preserve the task and measured computation. Do not add installs, shell/subprocess execution,
network access, credentials, mocks, fake metrics, fake predictions, hardcoded success, or validation bypasses."""


def runtime_code_repair_user_prompt(error: str, code: str, intent_type: str, task_type: str, task_name: str) -> str:
    return (
        f"Intent: {intent_type}\nTask type: {task_type}\nTask name: {task_name}\n"
        f"Runtime error:\n{error[:12000]}\n\nGenerated code:\n{code[:100000]}"
    )


def _route(intent_type: str, task_type: str, task_name: str, description: str) -> str:
    intent = intent_type.strip().lower()
    task = task_type.strip().lower()
    text = f"{task_name}\n{description}".lower()
    if intent == "paper_reproduction" or task in {"paper_parse", "paper_code_execute", "paper_compare", "fix_and_rerun"} or "论文复现" in text:
        return "paper"
    if intent == "framework_evaluation" or task in {"framework_research", "framework_report", "framework_recommendation"} or "框架对比" in text:
        return "framework"
    return "generic"
