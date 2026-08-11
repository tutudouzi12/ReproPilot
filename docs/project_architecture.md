# ReproPilot 系统架构

## 1. 定位

ReproPilot 是一个单机科研执行 Agent。它将论文复现、框架评测、代码执行和自有数据 Benchmark 转换为可持久化 DAG，在受限 Docker Sandbox 中运行代码，并把日志、指标和证据 Artifact 推送到 React 工作台。

系统强调“可执行、可恢复、可审计”：模型负责提出结构化内容，确定性 Python 组件负责路径、状态、预算、指标和证据校验。

## 2. 服务拓扑

```text
Browser / React Workbench
          │ REST + SSE
          ▼
FastAPI Backend
  ├─ Intent Router / Planner
  ├─ asyncio DAG Scheduler
  ├─ Agent Runtime
  ├─ FilePlanStore / EventBus
  └─ Upload / PDF Security
          │ internal Bearer Token
          ▼
FastAPI Docker Sandbox
          │ docker-py
          ▼
Isolated Python Containers
```

目录职责：

| 目录 | 职责 |
|---|---|
| `backend/app/main.py` | API、身份、上传、SSE、PDF 代理和健康检查 |
| `backend/app/planner.py` | 意图路由、DAG 模板和预算输入 |
| `backend/app/scheduler.py` | 状态机、并发、租约、重试、预算和 Artifact |
| `backend/app/agents.py` | Agent 路由、模型调用、Sandbox Client 和结构化输出 |
| `backend/app/repository.py` | 仓库发现、候选回退、工作区和入口评分 |
| `backend/app/research_coding.py` | 论文代码补丁、校验、回滚和重跑 |
| `backend/app/benchmark*.py` | 数据契约、Adapter、预检、执行和指标重算 |
| `backend/app/claim_evidence.py` | Claim Rubric 与 Evidence Graph |
| `docker-sandbox/app/main.py` | 容器生命周期、资源限制、命令执行和 NDJSON |
| `frontend/src` | 对话、DAG、PDF、节点日志和 Artifact 展示 |

## 3. 请求与规划

`POST /api/plan` 执行以下步骤：

1. 根据 Header 或匿名 Cookie 建立用户与会话身份。
2. 校验附件所有权，内部解析文本摘录，外部响应移除存储路径和摘录。
3. 识别 `Paper_Reproduction`、`Framework_Evaluation`、`Custom_Benchmark`、`Code_Execution` 或 `General`。
4. 解析指定仓库、论文标题、smoke/full 模式、样本上限和消融预算。
5. 生成带显式依赖、输入 Artifact、输出 Artifact、工具权限、超时和重试的 `PlanGraph`。
6. 高风险或 full 计划进入 `awaiting_approval`，批准后才可执行。

Planner 使用确定性图模板保证拓扑可审计；模型生成发生在具体 Agent 节点内，并通过 Pydantic 或 JSON 合约验证。

## 4. DAG 调度与租约

Scheduler 每轮根据依赖状态把节点从 `pending` 提升为 `ready`，按优先级选择最多 `MAX_CONCURRENT_TASKS` 个节点并发运行。

每次执行写入：

- `execution_id`：本次尝试的唯一标识；
- `execution_epoch`：重试、取消或转交时递增；
- `lease_owner` / `lease_expires_at`：执行者和租约期限；
- `run_count`、任务超时和全图尝试/时长预算。

Agent 返回后，Scheduler 会重新读取持久化租约。三项租约信息任何一项不一致，结果都会以 `task_result_discarded` 记录，不能覆盖转交或取消后的新状态。

失败节点在重试额度内回到 `pending`；额度耗尽后变为 `failed`，依赖它的节点变为 `blocked`。计划达到尝试或时长预算时，剩余节点被取消。

## 5. 持久化与事件

`FilePlanStore` 保存完整计划和事件历史：

- 写入临时文件并 `fsync`；
- 原子替换正式快照；
- 返回深拷贝，避免调用者绕过 Store 修改共享状态；
- 服务启动时把中断节点恢复为 `pending`，清除旧执行租约。

事件类型包括 `task_ready`、`task_started`、`task_log`、`artifact_created`、任务终态和计划终态。SSE 先订阅再读取历史，通过事件指纹消除竞态重复；重连客户端可以回放到终态。

Artifact 保存 `key`、`type`、`producer_task_id`、值、结构化结果和创建时间。Claim Rubric 与 Evidence Graph 使用明确的 `json` 类型，指标、报告、代码和图片也有独立类型。

## 6. Agent 与研究执行

| Agent | 主要任务 |
|---|---|
| Librarian | 论文解析、框架资料和 Claim Rubric |
| Coder | 仓库发现、准备、依赖分析和普通代码生成 |
| Research Coding | 论文调试、受限补丁、自有数据 Adapter 和 Benchmark |
| Sandbox | 运行时创建、依赖安装和代码执行 |
| Data | 指标分析、论文对比、报告、图表和 Evidence Graph |

Prompt 根据论文、框架、普通代码和报告任务隔离。LLM 输出必须满足结构化契约。运行时默认严格失败；显式离线演示只生成带 `unverified_demo` 标记的受限结果，不推断缺失论文主张或真实指标，也不会进入有效 Evidence Graph。

## 7. 仓库复现

仓库链路先使用用户指定 GitHub URL，否则根据结构化论文信息选择可信候选。准备阶段会：

- 规范化并校验 GitHub URL；
- 在候选间回退；
- 使用计划 ID 建立确定性工作区；
- 校验远端指纹，避免复用错误仓库；
- 验证附件 SHA-256 并拒绝符号链接越界；
- 对入口文件评分并生成受限 smoke runner；
- 根据 CPU、内存、磁盘和 GPU 决定 smoke/full 模式。

Research Coding Agent 只允许修改模型已看到的工作区文件。补丁写入前校验路径和禁止副作用，记录前后 SHA-256；执行失败或修复预算耗尽时恢复原文件。

## 8. Benchmark 与可信指标

自有数据 Benchmark 分为：

1. `dataset_profile`：读取 CSV/TSV/JSON/JSONL，校验列和数据 SHA-256。
2. `benchmark_adapter_generate`：生成只访问受限文件的 Adapter。
3. `benchmark_adapter_preflight`：最多三轮小样本运行与修复。
4. `benchmark_execute`：正式运行并生成逐样本预测、manifest 和指标。
5. `benchmark_validate`：重新读取预测，校验数据未变、样本数一致，并重算分类或回归指标。

模型不能自行宣布 Benchmark 成功，也不能用汇总文本替代逐样本预测。

## 9. Claim-to-Evidence 与消融

论文执行前冻结规范化 Rubric 和 SHA-256；执行后 Evidence Graph 只允许引用已存在的 Artifact。证据不足时状态降级为 `partially_reproduced`、`unverifiable` 或 `blocked_by_missing_asset`，不能把 smoke 结果写成完整论文复现。

ToT 消融先生成不同类别候选，再按实验数、GPU 分钟和总时长预算选择。选中的类别会生成不同 attention smoke 配置，而不是只改变报告文字。

## 10. Sandbox 安全边界

Sandbox Service 使用独立 Token 保护执行路由，并对容器设置：

- 镜像白名单和挂载根目录白名单；
- 默认关闭网络；
- CPU、内存和 PID 限制；
- `cap_drop=ALL` 与 `no-new-privileges`；
- 可选 GPU `DeviceRequest`；
- 命令级超时；
- 保留头尾且不破坏 UTF-8 的输出截断；
- NDJSON stdout/stderr chunk 和 final 事件。

Docker socket 仍代表较高宿主机权限，因此当前定位是受控单机研究原型，不是生产级不可信多租户平台。

## 11. 部署与验证

`docker-compose.yml` 启动 Frontend、Backend 和 Sandbox。Backend 与宿主 Docker 通过受限 `/tmp/repropilot-workspaces` 共享仓库工作区；Sandbox 健康后 Backend 才启动，Frontend 再等待 Backend 健康。

自动化验证包括 Backend pytest、Sandbox pytest、前端 lint/build 和 CI。真实 Docker、GPU 与完整论文训练的结论必须来自对应环境中的集成运行，不能由单元测试或离线模式替代。
