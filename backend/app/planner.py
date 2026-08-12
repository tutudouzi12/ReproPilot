from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .models import GraphEdge, IntentContext, PlanGraph, TaskContract, TaskNode


AGENT_TOOLS = {
    "coder_agent": ["repository.read", "workspace.write", "code.generate"],
    "sandbox_agent": ["sandbox.create", "sandbox.command", "sandbox.python", "sandbox.delete"],
    "librarian_agent": ["paper.search", "paper.read", "repository.discover"],
    "data_agent": ["artifact.read", "metrics.analyze", "report.write"],
    "research_coding_agent": [
        "repository.read",
        "repository.patch_scoped",
        "dataset.profile",
        "workspace.write_scoped",
        "sandbox.command",
        "metrics.validate",
    ],
}


class Planner:
    """Deterministic parity planner with a stable boundary for a future LLM planner."""

    def classify(self, intent: str) -> IntentContext:
        lowered = intent.lower()
        entities: dict[str, Any] = {}
        constraints: dict[str, Any] = {}
        repo = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", intent)
        if repo:
            entities["preferred_repo_url"] = repo.group(0).removesuffix(".git")
        arxiv = re.search(r"\b\d{4}\.\d{4,5}\b", intent)
        if arxiv:
            entities["paper_arxiv_id"] = arxiv.group(0)
        title = self._extract_paper_title(intent)
        if title:
            entities["paper_title"] = title

        reproduction = any(word in lowered for word in ("复现", "reproduce", "replicate", "论文", "paper", "arxiv", "实现算法"))
        framework = any(word in lowered for word in (
            "对比", "比较", "评估", "选型", "哪个好", "区别", "rag", "langchain", "llamaindex",
            "haystack", "dspy", "autogen", "crewai", "langgraph", "framework", "框架", " vs ",
        ))
        custom_benchmark = any(word in lowered for word in ("benchmark", "基准测试", "跑分")) and any(
            word in lowered for word in ("csv", "jsonl", "数据集", "输入列", "标签列", "自有数据")
        )
        code = any(word in lowered for word in (
            "计算", "代码", "运行", "执行", "画图", "写一个", "生成代码", "plot", "matplotlib", "numpy", "python",
        ))
        plot_request = any(word in lowered for word in (
            "plot", "matplotlib", "画图", "图表", "正弦", "余弦", "曲线",
        ))
        if custom_benchmark:
            kind = "Custom_Benchmark"
            entities["needs_custom_benchmark"] = True
        elif reproduction:
            kind = "Paper_Reproduction"
        elif plot_request:
            # "对比图" describes a visualization, not a framework comparison.
            kind = "Code_Execution"
        elif framework:
            kind = "Framework_Evaluation"
        elif code:
            kind = "Code_Execution"
        else:
            kind = "General"

        if kind == "Paper_Reproduction":
            if any(word in lowered for word in ("smoke", "最小实验", "最小验证", "快速验证")):
                entities["smoke_reproduction"] = True
                constraints["reproduction_mode"] = "smoke"
            elif any(word in lowered for word in ("full", "bleu", "wmt14", "完整复现", "全量复现", "真实复现")):
                entities["full_reproduction"] = True
                constraints["reproduction_mode"] = "full"
            for key, words in {
                "needs_plot": ("plot", "画图", "画出", "图表", "可视化"),
                "needs_fix": ("debug", "fix", "修复", "排查", "不一致", "重跑"),
                "needs_ablation": ("ablation", "消融", "参数敏感性", "模块移除", "随机种子"),
            }.items():
                if any(word in lowered for word in words):
                    entities[key] = True
        if kind == "Framework_Evaluation":
            entities["frameworks"] = self._frameworks(intent)
            entities["needs_benchmark"] = any(word in lowered for word in ("benchmark", "性能", "评测", "latency", "吞吐", "运行", "实验", "rag"))
        return IntentContext(
            raw_intent=intent,
            intent_type=kind,
            entities=entities,
            constraints=constraints,
            metadata={"normalized_intent": lowered.strip()},
            confidence=0.8,
            reasoning="deterministic API fallback classifier",
            source="rule_fallback",
        )

    def build_plan(self, context: IntentContext) -> PlanGraph:
        builders = {
            "AutoResearch": self._autoresearch,
            "Paper_Reproduction": self._paper_reproduction,
            "Framework_Evaluation": self._framework_evaluation,
            "Code_Execution": self._code_execution,
            "Custom_Benchmark": self._custom_benchmark,
            "General": self._general,
        }
        nodes = builders.get(context.intent_type, self._general)(context)
        edges = [
            GraphEdge(id=f"{dep}-{node.id}", **{"from": dep}, to=node.id)
            for node in nodes
            for dep in node.dependencies
        ]
        plan = PlanGraph(
            user_intent=context.raw_intent,
            intent_type=context.intent_type,
            nodes=nodes,
            edges=edges,
        )
        plan.refresh_meta()
        return plan

    def _node(
        self,
        node_id: str,
        name: str,
        task_type: str,
        agent: str,
        deps: list[str] | None,
        required: list[str] | None,
        outputs: list[str] | None,
        context: IntentContext,
        parallel: bool = True,
        inputs: dict[str, Any] | None = None,
    ) -> TaskNode:
        return TaskNode(
            id=node_id,
            name=name,
            type=task_type,
            description=f"{name}\n原始目标：{context.raw_intent}",
            assigned_to=agent,
            dependencies=deps or [],
            required_artifacts=required or [],
            output_artifacts=outputs or [],
            parallelizable=parallel,
            priority=50,
            retry_limit=1,
            inputs=inputs or {},
            contract=TaskContract(
                input_artifacts=required or [],
                output_artifacts=outputs or [],
                allowed_tools=AGENT_TOOLS.get(agent, ["conversation.respond"]),
            ),
        )

    def _paper_reproduction(self, context: IntentContext) -> list[TaskNode]:
        title = str(context.entities.get("paper_title", "Paper"))
        parse = self._node("paper_parse", f"解析 {title} 并提取方法", "paper_parse", "librarian_agent", [], [], ["parsed_paper"], context)
        if context.entities.get("uploaded_files"):
            parse.inputs["uploaded_files"] = context.entities["uploaded_files"]
        rubric = self._node("claim_rubric", "冻结分层主张验收标准", "claim_rubric_extract", "librarian_agent", [parse.id], ["parsed_paper"], ["claim_rubric", "claim_rubric_report"], context)
        discover_inputs = {key: context.entities[key] for key in ("preferred_repo_url", "paper_arxiv_id", "paper_title") if key in context.entities}
        discover = self._node("repo_discovery", "查找并验证开源仓库", "repo_discovery", "coder_agent", [parse.id], ["parsed_paper"], ["candidate_repositories", "repo_validation_report", "repo_url"], context, inputs=discover_inputs)
        prepare_deps = [discover.id]
        prepare_required = ["repo_url", "candidate_repositories", "repo_validation_report"]
        nodes = [parse, rubric, discover]
        if context.entities.get("needs_ablation"):
            ablation = self._node("ablation_design", "设计受限消融实验", "ablation_design", "data_agent", [parse.id], ["parsed_paper"], ["ablation_plan", "selected_ablation_configs", "ablation_selection_report"], context, inputs=self._ablation_inputs(context.raw_intent))
            nodes.append(ablation)
            prepare_deps.append(ablation.id)
            prepare_required.extend(["ablation_plan", "selected_ablation_configs"])
        mode_inputs = self._reproduction_inputs(context)
        prepare = self._node("repo_prepare", "准备论文仓库工作区", "repo_prepare", "coder_agent", prepare_deps, prepare_required, ["workspace_path", "code_file_path", "generated_code", "repo_manifest", "reproduction_mode_report"], context, False, mode_inputs)
        resolve = self._node("resolve_dependencies", "解析论文仓库依赖", "resolve_dependencies", "coder_agent", [prepare.id], ["workspace_path", "code_file_path", "generated_code", "repo_manifest"], ["dependency_spec"], context, False)
        runtime = self._node("prepare_runtime", "创建隔离运行环境", "prepare_runtime", "sandbox_agent", [resolve.id], ["workspace_path", "dependency_spec"], ["runtime_session"], context, False)
        install = self._node("install_dependencies", "安装论文仓库依赖", "install_dependencies", "sandbox_agent", [runtime.id], ["workspace_path", "runtime_session", "dependency_spec"], ["prepared_runtime", "dependency_install_report"], context, False)
        baseline = self._node("paper_code_execute", "执行并调试基线实验", "paper_code_execute", "research_coding_agent", [install.id], ["workspace_path", "code_file_path", "generated_code", "prepared_runtime", "repo_manifest"], ["run_metrics", "paper_debug_report", "paper_patch_manifest"], context, False)
        compare = self._node("paper_compare", "将实验结果与论文主张对比", "paper_compare", "data_agent", [baseline.id], ["run_metrics", "paper_debug_report", "parsed_paper", "repo_manifest", "reproduction_mode_report"], ["comparison_report"], context, False)
        nodes.extend([prepare, resolve, runtime, install, baseline, compare])
        last = compare
        evidence_required = ["claim_rubric", "parsed_paper", "repo_manifest", "reproduction_mode_report", "dependency_install_report", "run_metrics", "paper_debug_report", "paper_patch_manifest", "comparison_report"]
        if context.entities.get("needs_fix"):
            fix = self._node("fix_and_rerun", "调试结果差异并重新运行", "fix_and_rerun", "research_coding_agent", [baseline.id, compare.id], ["workspace_path", "code_file_path", "generated_code", "prepared_runtime", "repo_manifest", "run_metrics", "paper_debug_report", "comparison_report"], ["rerun_metrics", "rerun_report", "gap_debug_report", "gap_patch_manifest"], context, False)
            nodes.append(fix)
            last = fix
            evidence_required.extend(["rerun_metrics", "rerun_report", "gap_debug_report", "gap_patch_manifest"])
        if context.entities.get("needs_plot"):
            artifact = "rerun_metrics" if last.type == "fix_and_rerun" else "comparison_report"
            plot = self._node("result_visualization", "可视化复现实验结果", "result_visualization", "data_agent", [last.id], [artifact], ["result_plot"], context)
            nodes.append(plot)
            last = plot
            evidence_required.append("result_plot")
        evidence = self._node("claim_evidence", "构建主张到证据图", "claim_evidence_build", "data_agent", [rubric.id, last.id], evidence_required, ["claim_evidence_graph", "claim_verification_report"], context, False)
        nodes.append(evidence)
        return nodes

    def _autoresearch(self, context: IntentContext) -> list[TaskNode]:
        uploads = self._strip_excerpts(context.entities.get("uploaded_files", []))
        revision = str(context.entities.get("repository_revision") or "")
        discover = self._node(
            "repo_discovery",
            "验证 AutoResearch 目标仓库",
            "repo_discovery",
            "coder_agent",
            [],
            [],
            ["candidate_repositories", "repo_validation_report", "repo_url"],
            context,
            inputs={key: context.entities[key] for key in ("preferred_repo_url",) if key in context.entities},
        )
        prepare = self._node(
            "repo_prepare",
            "按精确提交准备研究工作区",
            "repo_prepare",
            "coder_agent",
            [discover.id],
            ["repo_url", "candidate_repositories", "repo_validation_report"],
            ["workspace_path", "code_file_path", "generated_code", "repo_manifest", "reproduction_mode_report"],
            context,
            False,
            {"requested_reproduction_mode": "smoke", "full_reproduction_requested": False, "uploaded_files": uploads, "repository_revision": revision},
        )
        freeze = self._node(
            "autoresearch_spec_freeze",
            "冻结 AutoResearch 规格与哈希",
            "autoresearch_spec_freeze",
            "research_coding_agent",
            [prepare.id],
            ["workspace_path", "repo_manifest"],
            ["research_spec", "research_spec_report"],
            context,
            False,
        )
        resolve = self._node("resolve_dependencies", "解析冻结研究依赖", "resolve_dependencies", "coder_agent", [freeze.id], ["workspace_path", "code_file_path", "generated_code", "repo_manifest", "research_spec"], ["dependency_spec"], context, False)
        runtime = self._node("prepare_runtime", "创建隔离研究运行时", "prepare_runtime", "sandbox_agent", [resolve.id], ["workspace_path", "dependency_spec"], ["runtime_session"], context, False)
        install = self._node("install_dependencies", "安装冻结依赖", "install_dependencies", "sandbox_agent", [runtime.id], ["workspace_path", "runtime_session", "dependency_spec"], ["prepared_runtime", "dependency_install_report"], context, False)
        run = self._node(
            "autoresearch_run",
            "执行受治理候选实验循环",
            "autoresearch_run",
            "research_coding_agent",
            [install.id],
            ["workspace_path", "repo_manifest", "prepared_runtime", "research_spec"],
            ["research_trial_ledger", "research_best_candidate", "research_best_metrics"],
            context,
            False,
        )
        validate = self._node(
            "autoresearch_validate",
            "执行独立重复与隐藏验收",
            "autoresearch_validate",
            "research_coding_agent",
            [run.id],
            ["workspace_path", "prepared_runtime", "research_spec", "research_trial_ledger", "research_best_candidate"],
            ["research_validation_report", "validated_research_metrics"],
            context,
            False,
        )
        for node in (prepare, resolve, runtime, install, freeze, run, validate):
            node.timeout_seconds = max(node.timeout_seconds, 900 if node.type in {"install_dependencies", "autoresearch_run", "autoresearch_validate"} else 300)
        return [discover, prepare, freeze, resolve, runtime, install, run, validate]

    def _framework_evaluation(self, context: IntentContext) -> list[TaskNode]:
        frameworks = list(context.entities.get("frameworks") or self._frameworks(context.raw_intent))
        research = self._node("framework_research", "调研候选框架", "framework_research", "librarian_agent", [], [], ["framework_research_report"], context)
        nodes = [research]
        if not context.entities.get("needs_benchmark"):
            fits = []
            for index, framework in enumerate(frameworks, 1):
                fit = self._node(f"framework_fit_{index}", f"分析 {framework} 适配性", f"framework_fit_{index}", "librarian_agent", [research.id], ["framework_research_report"], [f"framework_fit_report_{index}"], context)
                nodes.append(fit)
                fits.append(fit)
            nodes.append(self._node("framework_report", "生成选型建议", "framework_recommendation", "data_agent", [n.id for n in fits], [f"framework_fit_report_{i}" for i in range(1, len(fits) + 1)], ["evaluation_report"], context, False))
            return nodes
        runs = []
        for index, framework in enumerate(frameworks, 1):
            prefix = re.sub(r"[^a-z0-9]+", "_", framework.lower()).strip("_") or f"framework_{index}"
            generate = self._node(f"{prefix}_generate", f"生成 {framework} Benchmark 代码", "generate_code", "coder_agent", [research.id], ["framework_research_report"], [f"{prefix}_generated_code"], context)
            resolve = self._node(f"{prefix}_resolve", f"解析 {framework} 依赖", "resolve_dependencies", "coder_agent", [generate.id], [f"{prefix}_generated_code"], [f"{prefix}_dependency_spec"], context)
            runtime = self._node(f"{prefix}_runtime", f"准备 {framework} 运行环境", "prepare_runtime", "sandbox_agent", [resolve.id], [f"{prefix}_dependency_spec"], [f"{prefix}_runtime_session"], context)
            install = self._node(f"{prefix}_install", f"安装 {framework} 依赖", "install_dependencies", "sandbox_agent", [runtime.id], [f"{prefix}_runtime_session", f"{prefix}_dependency_spec"], [f"{prefix}_prepared_runtime", f"{prefix}_dependency_install_report"], context)
            run = self._node(f"{prefix}_run", f"运行 {framework} Benchmark", "execute_code", "sandbox_agent", [install.id], [f"{prefix}_generated_code", f"{prefix}_prepared_runtime"], [f"framework_metrics_{index}"], context)
            nodes.extend([generate, resolve, runtime, install, run])
            runs.append(run)
        nodes.append(self._node("framework_report", "生成基准测试报告", "framework_report", "data_agent", [n.id for n in runs], [f"framework_metrics_{i}" for i in range(1, len(runs) + 1)], ["evaluation_report"], context, False))
        return nodes

    def _custom_benchmark(self, context: IntentContext) -> list[TaskNode]:
        common = self._benchmark_inputs(context.raw_intent)
        uploads = context.entities.get("uploaded_files", [])
        profile = self._node("dataset_profile", "分析上传数据集", "dataset_profile", "research_coding_agent", [], [], ["dataset_manifest"], context, inputs={**common, "uploaded_files": uploads})
        discover = self._node("repo_discovery", "获取评测目标仓库", "repo_discovery", "coder_agent", [], [], ["candidate_repositories", "repo_validation_report", "repo_url"], context, inputs={key: context.entities[key] for key in ("preferred_repo_url",) if key in context.entities})
        prepare = self._node("repo_prepare", "准备评测工作区", "repo_prepare", "coder_agent", [discover.id], ["repo_url", "candidate_repositories", "repo_validation_report"], ["workspace_path", "code_file_path", "generated_code", "repo_manifest", "reproduction_mode_report"], context, False, {"requested_reproduction_mode": "smoke", "full_reproduction_requested": False, "uploaded_files": self._strip_excerpts(uploads)})
        specs = [
            ("benchmark_adapter_generate", "生成仓库评测适配器", "research_coding_agent", [profile.id, prepare.id], ["dataset_manifest", "workspace_path", "repo_manifest"], ["benchmark_adapter_plan", "benchmark_adapter_spec", "benchmark_generated_code", "benchmark_code_file_path", "benchmark_adapter_report"]),
            ("resolve_dependencies", "解析评测依赖", "coder_agent", ["benchmark_adapter_generate"], ["workspace_path", "repo_manifest", "benchmark_generated_code", "benchmark_code_file_path"], ["dependency_spec"]),
            ("prepare_runtime", "准备评测运行环境", "sandbox_agent", ["resolve_dependencies"], ["workspace_path", "dependency_spec"], ["runtime_session"]),
            ("install_dependencies", "安装评测依赖", "sandbox_agent", ["prepare_runtime"], ["workspace_path", "runtime_session", "dependency_spec"], ["prepared_runtime", "dependency_install_report"]),
            ("benchmark_adapter_preflight", "预检并修复评测适配器", "research_coding_agent", ["install_dependencies"], ["workspace_path", "dataset_manifest", "benchmark_adapter_spec", "benchmark_generated_code", "benchmark_code_file_path", "prepared_runtime"], ["validated_benchmark_adapter_spec", "validated_benchmark_generated_code", "validated_benchmark_code_file_path", "benchmark_preflight_report"]),
            ("benchmark_execute", "执行自定义数据评测", "research_coding_agent", ["benchmark_adapter_preflight"], ["workspace_path", "dataset_manifest", "validated_benchmark_adapter_spec", "validated_benchmark_generated_code", "validated_benchmark_code_file_path", "prepared_runtime"], ["benchmark_run_metrics", "benchmark_run_manifest", "benchmark_predictions_path", "benchmark_execution_report"]),
            ("benchmark_validate", "校验评测证据", "research_coding_agent", ["benchmark_execute"], ["workspace_path", "dataset_manifest", "benchmark_run_metrics", "benchmark_run_manifest", "benchmark_predictions_path"], ["benchmark_metrics", "benchmark_validation_report"]),
            ("framework_report", "生成可信评测报告", "data_agent", ["benchmark_validate"], ["benchmark_metrics", "benchmark_validation_report", "validated_benchmark_adapter_spec"], ["evaluation_report"]),
        ]
        nodes = [profile, discover, prepare]
        for task_type, name, agent, deps, required, outputs in specs:
            node = self._node(task_type, name, task_type, agent, deps, required, outputs, context, False, deepcopy(common) if task_type in {"benchmark_adapter_generate", "benchmark_adapter_preflight", "benchmark_execute"} else None)
            nodes.append(node)
        return nodes

    def _code_execution(self, context: IntentContext) -> list[TaskNode]:
        specs = [
            ("generate_code", "生成代码", "coder_agent", [], [], ["generated_code"], True),
            ("resolve_dependencies", "解析依赖", "coder_agent", ["generate_code"], ["generated_code"], ["dependency_spec"], True),
            ("prepare_runtime", "准备运行环境", "sandbox_agent", ["resolve_dependencies"], ["dependency_spec"], ["runtime_session"], False),
            ("install_dependencies", "安装依赖", "sandbox_agent", ["prepare_runtime"], ["runtime_session", "dependency_spec"], ["prepared_runtime", "dependency_install_report"], False),
            ("execute_code", "执行代码", "sandbox_agent", ["install_dependencies"], ["generated_code", "prepared_runtime"], ["execution_result"], False),
        ]
        nodes = [self._node(task_type, name, task_type, agent, deps, required, outputs, context, parallel) for task_type, name, agent, deps, required, outputs, parallel in specs]
        lowered = context.raw_intent.lower()
        last = nodes[-1]
        if any(word in lowered for word in ("plot", "matplotlib", "画图", "图表", "正弦", "余弦", "曲线")):
            last = self._node("render_plot", "渲染输出图表", "render_plot", "data_agent", [last.id], ["execution_result"], ["plot_image"], context)
            nodes.append(last)
        if any(word in lowered for word in ("分析", "解释", "report", "报告", "复杂度")) or last.id == "execute_code":
            nodes.append(self._node("verify_result", "校验并总结结果", "verify_result", "data_agent", [last.id], [last.output_artifacts[-1]], ["verification_report"], context))
        return nodes

    def _general(self, context: IntentContext) -> list[TaskNode]:
        collect = self._node("collect_context", "收集背景信息", "general_research", "librarian_agent", [], [], ["background_context"], context)
        answer = self._node("synthesize_response", "综合生成回答", "general_response", "data_agent", [collect.id], ["background_context"], ["general_response"], context, False)
        return [collect, answer]

    @staticmethod
    def _extract_paper_title(intent: str) -> str | None:
        for pattern in (r"《([^》]{2,200})》", r"[\"']([^\"']{3,200})[\"']"):
            match = re.search(pattern, intent)
            if match:
                return match.group(1).strip()
        if "attention is all you need" in intent.lower():
            return "Attention Is All You Need"
        return None

    @staticmethod
    def _frameworks(intent: str) -> list[str]:
        known = {
            "langchain": "LangChain", "llamaindex": "LlamaIndex", "llama_index": "LlamaIndex",
            "langgraph": "LangGraph", "haystack": "Haystack", "dspy": "DSPy", "autogen": "AutoGen", "crewai": "CrewAI",
        }
        found = [display for key, display in known.items() if key in intent.lower()]
        return list(dict.fromkeys(found)) or ["Framework A", "Framework B"]

    @staticmethod
    def _bounded(raw: str, patterns: list[str], fallback: int, minimum: int, maximum: int) -> int:
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                return max(minimum, min(maximum, int(match.group(1))))
        return fallback

    def _ablation_inputs(self, raw: str) -> dict[str, Any]:
        return {
            "ablation_max_experiments": self._bounded(raw, [r"(?:最多|max(?:imum)?)\s*(\d+)\s*(?:组|个|项|次)?.*?(?:消融|实验|ablations?|experiments?)"], 3, 1, 6),
            "ablation_max_gpu_minutes": self._bounded(raw, [r"gpu.*?(\d+)\s*(?:minutes?|分钟)"], 30, 0, 1440),
            "ablation_max_wall_minutes": self._bounded(raw, [r"(?:总耗时|总时长|wall(?:[- ]?time)?).*?(\d+)\s*(?:minutes?|分钟)"], 60, 5, 1440),
            "ablation_strategy": "bounded_tree_of_thoughts",
        }

    def _benchmark_inputs(self, raw: str) -> dict[str, Any]:
        inputs: dict[str, Any] = {
            "benchmark_max_preflight_attempts": 3,
            "benchmark_max_samples": self._bounded(raw, [r"(?:最多|最大|max(?:imum)?)\s*(\d+)\s*(?:条|个|rows?|samples?|样本)"], 1000, 1, 100000),
        }
        for key, pattern in {
            "benchmark_input_column": r"(?:输入列|input(?:\s+column)?)\s*(?:是|为|[:：=])?\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]*)",
            "benchmark_target_column": r"(?:标签列|目标列|label(?:\s+column)?|target(?:\s+column)?)\s*(?:是|为|[:：=])?\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]*)",
        }.items():
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                inputs[key] = match.group(1)
        return inputs

    @staticmethod
    def _strip_excerpts(uploads: Any) -> Any:
        if not isinstance(uploads, list):
            return uploads
        return [{key: value for key, value in item.items() if key != "text_excerpt"} if isinstance(item, dict) else item for item in uploads]

    def _reproduction_inputs(self, context: IntentContext) -> dict[str, Any]:
        raw = context.raw_intent.lower()
        smoke = bool(context.entities.get("smoke_reproduction")) or any(word in raw for word in ("smoke", "最小实验", "最小验证", "快速验证"))
        explicit_full = any(word in raw for word in ("full reproduction", "full run", "run wmt", "完整复现", "全量复现", "采用 full"))
        full = bool(context.entities.get("full_reproduction")) or any(word in raw for word in ("bleu", "wmt14", "完整复现", "全量复现"))
        if smoke and not explicit_full:
            full = False
        mode = str(context.constraints.get("reproduction_mode") or ("full" if full else "smoke" if smoke else "auto"))
        inputs: dict[str, Any] = {"requested_reproduction_mode": mode, "full_reproduction_requested": full}
        if "uploaded_files" in context.entities:
            inputs["uploaded_files"] = self._strip_excerpts(context.entities["uploaded_files"])
        return inputs
