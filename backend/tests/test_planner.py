from __future__ import annotations

from app.planner import Planner


def by_type(plan, task_type):
    return next(node for node in plan.nodes if node.type == task_type)


def test_intent_priority_matches_original_routes():
    planner = Planner()
    assert planner.classify("比较 LangChain 和 LlamaIndex 的 RAG 最小实验").intent_type == "Framework_Evaluation"
    assert planner.classify("介绍一下多智能体系统的基本概念").intent_type == "General"
    assert planner.classify("复现论文并与论文指标对比").intent_type == "Paper_Reproduction"
    assert planner.classify("写一段 Python 代码并运行").intent_type == "Code_Execution"


def test_smoke_mode_overrides_negated_full_metric():
    planner = Planner()
    context = planner.classify("明确采用 smoke，不训练 WMT14，不做论文 BLEU 复现")
    plan = planner.build_plan(context)
    inputs = by_type(plan, "repo_prepare").inputs
    assert inputs["requested_reproduction_mode"] == "smoke"
    assert inputs["full_reproduction_requested"] is False


def test_plot_comparison_is_not_misrouted_as_framework_evaluation():
    planner = Planner()
    context = planner.classify("帮我画一个正弦函数和余弦函数的对比图")
    assert context.intent_type == "Code_Execution"
    assert [node.type for node in planner.build_plan(context).nodes][-1] == "render_plot"


def test_preferred_repository_is_preserved():
    planner = Planner()
    context = planner.classify(
        "复现 Attention Is All You Need，使用 https://github.com/harvardnlp/annotated-transformer"
    )
    plan = planner.build_plan(context)
    assert by_type(plan, "repo_discovery").inputs["preferred_repo_url"] == "https://github.com/harvardnlp/annotated-transformer"


def test_bounded_ablation_is_inserted_into_paper_graph():
    planner = Planner()
    context = planner.classify("复现 Transformer 并做最多 2 组轻量消融，总耗时 30 分钟，GPU 时间不超过 10 分钟")
    plan = planner.build_plan(context)
    design = by_type(plan, "ablation_design")
    prepare = by_type(plan, "repo_prepare")
    assert design.inputs["ablation_max_experiments"] == 2
    assert design.inputs["ablation_max_wall_minutes"] == 30
    assert design.inputs["ablation_max_gpu_minutes"] == 10
    assert "ablation_plan" in prepare.required_artifacts


def test_custom_benchmark_builds_eleven_node_harness():
    planner = Planner()
    context = planner.classify(
        "用 https://github.com/example/research-repo 对自有 CSV 数据集跑 benchmark，输入列是 review，标签列是 label，最多 64 条样本"
    )
    context.entities["uploaded_files"] = [{
        "id": "upload-1",
        "name": "reviews.csv",
        "storage_path": "/tmp/reviews.csv",
        "text_excerpt": "review,label",
    }]
    plan = planner.build_plan(context)
    assert plan.intent_type == "Custom_Benchmark"
    assert [node.type for node in plan.nodes] == [
        "dataset_profile",
        "repo_discovery",
        "repo_prepare",
        "benchmark_adapter_generate",
        "resolve_dependencies",
        "prepare_runtime",
        "install_dependencies",
        "benchmark_adapter_preflight",
        "benchmark_execute",
        "benchmark_validate",
        "framework_report",
    ]
    assert plan.nodes[0].inputs["benchmark_input_column"] == "review"
    assert plan.nodes[0].inputs["benchmark_target_column"] == "label"
    assert "text_excerpt" not in plan.nodes[2].inputs["uploaded_files"][0]
    assert by_type(plan, "benchmark_execute").inputs["benchmark_max_samples"] == 64


def test_claim_aware_debug_flow_has_final_evidence_join():
    planner = Planner()
    plan = planner.build_plan(planner.classify("复现 Transformer，遇到论文代码错误时调试，并画出重跑结果"))
    baseline = by_type(plan, "paper_code_execute")
    fix = by_type(plan, "fix_and_rerun")
    plot = by_type(plan, "result_visualization")
    evidence = by_type(plan, "claim_evidence_build")
    assert baseline.assigned_to == "research_coding_agent"
    assert fix.assigned_to == "research_coding_agent"
    assert plot.dependencies == [fix.id]
    assert evidence.dependencies == ["claim_rubric", plot.id]
    for artifact in ("claim_rubric", "run_metrics", "comparison_report", "rerun_metrics", "result_plot"):
        assert artifact in evidence.required_artifacts


def test_framework_benchmark_uses_isolated_branches():
    planner = Planner()
    plan = planner.build_plan(planner.classify("比较 LangChain 和 LlamaIndex 在同一个 RAG 场景的 benchmark"))
    assert plan.intent_type == "Framework_Evaluation"
    execute_nodes = [node for node in plan.nodes if node.type == "execute_code"]
    runtime_nodes = [node for node in plan.nodes if node.type == "prepare_runtime"]
    assert len(execute_nodes) == 2
    assert len(runtime_nodes) == 2
    assert execute_nodes[0].required_artifacts != execute_nodes[1].required_artifacts


def test_autoresearch_builds_fixed_eight_node_harness():
    planner = Planner()
    context = planner.classify("对 https://github.com/example/research-repo 做 AutoResearch")
    context.intent_type = "AutoResearch"
    context.entities["uploaded_files"] = [{"id": "spec-1", "name": "autoresearch.json", "storage_path": "/tmp/autoresearch.json", "text_excerpt": "hidden"}]
    context.entities["repository_revision"] = "a" * 40
    plan = planner.build_plan(context)
    assert [node.type for node in plan.nodes] == [
        "repo_discovery",
        "repo_prepare",
        "autoresearch_spec_freeze",
        "resolve_dependencies",
        "prepare_runtime",
        "install_dependencies",
        "autoresearch_run",
        "autoresearch_validate",
    ]
    prepare = by_type(plan, "repo_prepare")
    assert prepare.inputs["repository_revision"] == "a" * 40
    assert "text_excerpt" not in prepare.inputs["uploaded_files"][0]
    assert by_type(plan, "autoresearch_run").assigned_to == "research_coding_agent"
    assert by_type(plan, "autoresearch_validate").required_artifacts == [
        "workspace_path", "prepared_runtime", "research_spec", "research_trial_ledger", "research_best_candidate"
    ]
