import pytest
import json

from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode
from app.prompts import (
    FRAMEWORK_MARKER,
    FRAMEWORK_REPORT_MARKER,
    FRAMEWORK_RESEARCH_MARKER,
    PAPER_MARKER,
    PAPER_REPORT_MARKER,
    PAPER_RESEARCH_MARKER,
    coder_system_prompt,
    data_system_prompt,
    librarian_system_prompt,
)


def test_task_prompt_isolation():
    framework_coder = coder_system_prompt("Framework_Evaluation", "generate_code", "Generate LangChain Benchmark")
    paper_coder = coder_system_prompt("Paper_Reproduction", "execute_code", "Execute Baseline")
    assert FRAMEWORK_MARKER in framework_coder and PAPER_MARKER not in framework_coder
    assert PAPER_MARKER in paper_coder and FRAMEWORK_MARKER not in paper_coder

    framework_report = data_system_prompt("Framework_Evaluation", "framework_report")
    paper_report = data_system_prompt("Paper_Reproduction", "paper_compare")
    assert FRAMEWORK_REPORT_MARKER in framework_report and PAPER_REPORT_MARKER not in framework_report
    assert PAPER_REPORT_MARKER in paper_report and FRAMEWORK_REPORT_MARKER not in paper_report

    framework_research = librarian_system_prompt("Framework_Evaluation", "framework_research")
    paper_research = librarian_system_prompt("Paper_Reproduction", "paper_parse")
    assert FRAMEWORK_RESEARCH_MARKER in framework_research and PAPER_RESEARCH_MARKER not in framework_research
    assert PAPER_RESEARCH_MARKER in paper_research and FRAMEWORK_RESEARCH_MARKER not in paper_research


def test_generic_prompt_does_not_leak_specialized_constraints():
    prompt = coder_system_prompt("Code_Execution", "generate_code", "Calculate mean")
    assert PAPER_MARKER not in prompt
    assert FRAMEWORK_MARKER not in prompt


@pytest.mark.asyncio
async def test_routed_executor_uses_task_isolated_system_prompt():
    class CapturingLLM:
        configured = True

        def __init__(self):
            self.systems = []

        async def complete(self, system, user):
            self.systems.append(system)
            return json.dumps({
                "status": "complete",
                "paper_title": "Verified Paper",
                "method_names": [],
                "datasets": [],
                "reported_metrics": {},
                "claims": [],
                "reproduction_requirements": [],
                "limitations": [],
                "summary": "verified response",
            })

    llm = CapturingLLM()
    executor = RoutedAgentExecutor(llm)
    node = TaskNode(
        name="Parse paper",
        type="paper_parse",
        description="论文复现材料解析",
        assigned_to="librarian_agent",
    )
    plan = PlanGraph(user_intent="复现论文", intent_type="Paper_Reproduction", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    assert result.status == "completed"
    assert PAPER_RESEARCH_MARKER in llm.systems[0]
    assert FRAMEWORK_RESEARCH_MARKER not in llm.systems[0]
