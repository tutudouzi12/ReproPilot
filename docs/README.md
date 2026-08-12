# 文档索引

ReproPilot 的运行说明以仓库根目录 `README.md` 和以下 Python 实现为准：

- `backend/app/main.py`：FastAPI 与前端 API 契约
- `backend/app/planner.py`：确定性 DAG Planner
- `backend/app/scheduler.py`：asyncio DAG Scheduler
- `backend/app/agents.py`：Agent 路由、模型与沙箱客户端
- `backend/app/store.py`：原子持久化和中断恢复
- `docker-sandbox/app/main.py`：Python Docker 沙箱
- `backend/tests`、`docker-sandbox/tests`：可执行测试

核心主题：

- `end-to-end-demo.md`：真实模型与 Docker 标准案例
- `design-decisions.md`：关键工程取舍、替代方案和已知限制
- `interview-guide.md`：Agent / AI 应用岗位的四点简历与面试表达
- `project_architecture.md`：系统组件、DAG 主链和安全边界
- `local_startup_guide.md`：本地与 Compose 启动方式
- `research_coding_agent.md`：论文调试、受限补丁和 Benchmark Harness
- `autoresearch.md`：冻结研究契约、重复候选实验、回滚与隐藏验收
- `claim_evidence_graph.md`：主张、Rubric、证据 Artifact 与判定状态
- `tot_ablation_and_uploads.md`：预算受限消融与附件路由
- `user_manual.md`：工作台使用说明
